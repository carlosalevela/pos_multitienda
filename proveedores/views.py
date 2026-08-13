import io
import re
import pdfplumber

from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa, scope_qs
from .models import Proveedor, Compra, DistribucionDetalle
from .serializers import ProveedorSerializer, ProveedorSimpleSerializer, CompraSerializer
from productos.models import Inventario, MovimientoInventario, Producto, generar_codigo_barras_interno
from contabilidad.models import Gasto


# ── Proveedores ───────────────────────────────────────────────

class ProveedorListCreateView(generics.ListCreateAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Proveedor.objects.filter(activo=True),
            campo_empresa="empresa",
        )
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(nombre__icontains=q)
        return qs.order_by("nombre")

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa_id")
            if not empresa_id:
                raise PermissionDenied(
                    "El superadmin debe especificar una empresa.")
            serializer.save(empresa_id=empresa_id)
        else:
            serializer.save(empresa=get_empresa(self.request))


class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Proveedor.objects.all()
        return Proveedor.objects.filter(
            empresa=get_empresa(self.request))

    def perform_update(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa_id")
            if empresa_id:
                serializer.save(empresa_id=empresa_id)
            else:
                serializer.save()
        else:
            serializer.save(empresa=get_empresa(self.request))

    def destroy(self, request, *args, **kwargs):
        proveedor = self.get_object()
        proveedor.activo = False
        proveedor.save()
        return Response(
            {"detail": f"Proveedor '{proveedor.nombre}' desactivado."})


class ProveedorSimpleListView(generics.ListAPIView):
    serializer_class   = ProveedorSimpleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Proveedor.objects.filter(activo=True)

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            tienda_id  = self.request.query_params.get("tienda_id")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
            elif tienda_id:
                qs = qs.filter(empresa__tienda__id=tienda_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        return qs.order_by("nombre")


# ── Compras ───────────────────────────────────────────────────

class CompraListCreateView(generics.ListCreateAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = scope_qs(
            self.request,
            Compra.objects.select_related(
                "proveedor", "tienda", "empleado"
            ).prefetch_related("detalles__distribuciones"),
            campo_empresa="proveedor__empresa",
        )

        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if estado:    qs = qs.filter(estado=estado)
        return qs.order_by("-fecha_orden")

    @transaction.atomic
    def perform_create(self, serializer):
        # Bloquea todos los registros OC-* para serializar creates concurrentes.
        # unique=True es global, así que el contador también debe serlo.
        numeros = (
            Compra.objects
            .select_for_update()
            .filter(numero_orden__startswith="OC-")
            .values_list("numero_orden", flat=True)
        )
        ultimo = 0
        for num in numeros:
            try:
                v = int(num[3:])
                if v > ultimo:
                    ultimo = v
            except ValueError:
                pass
        numero = f"OC-{(ultimo + 1):05d}"
        serializer.save(
            empleado=self.request.user,
            numero_orden=numero,
        )


class CompraDetailView(generics.RetrieveAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Compra.objects.prefetch_related("detalles__producto", "detalles__distribuciones")
        return Compra.objects.filter(
            proveedor__empresa=get_empresa(self.request)
        ).prefetch_related("detalles__producto", "detalles__distribuciones")


class RecibirCompraView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        try:
            qs     = Compra.objects.prefetch_related(
                "detalles__producto", "detalles__categoria",
                "detalles__distribuciones__tienda")
            compra = qs.get(pk=pk) if es_superadmin(request) \
                else qs.get(pk=pk,
                            proveedor__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response(
                {"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "Esta compra ya fue recibida."}, status=400)
        if compra.estado == "cancelada":
            return Response(
                {"error": "No se puede recibir una compra cancelada."},
                status=400)

        # precios:        {str(detalleId): precioVenta}
        # precios_mayoreo:{str(detalleId): precioMayoreo}
        precios_venta   = request.data.get('precios', {})
        precios_mayoreo = request.data.get('precios_mayoreo', {})

        # Superadmin: inferir empresa desde el proveedor de la compra
        empresa = get_empresa(request) or compra.proveedor.empresa
        empleado_obj           = request.user
        productos_actualizados = []

        for detalle in compra.detalles.all():
            # Crear producto nuevo si es modo libre
            if not detalle.producto:
                # Usar código ingresado por el usuario, o generar uno interno
                codigo = (detalle.codigo_barras_input or '').strip() or generar_codigo_barras_interno()
                # Precio de venta inicial: el que vino del PDF preview, o el costo
                pv_inicial = float(detalle.precio_venta) if detalle.precio_venta else float(detalle.precio_unitario)
                nuevo_producto = Producto.objects.create(
                    nombre        = detalle.nombre_libre or "Producto sin nombre",
                    categoria     = detalle.categoria,
                    precio_compra = detalle.precio_unitario,
                    precio_venta  = pv_inicial,
                    codigo_barras = codigo,
                    empresa       = empresa,
                    activo        = True,
                )
                detalle.producto = nuevo_producto
                detalle.save()

            producto        = detalle.producto
            detalle_id_str  = str(detalle.id)
            # El precio_venta del modal tiene prioridad; si no lo hay, usa el del detalle
            precio_venta_nuevo   = precios_venta.get(detalle_id_str)
            if precio_venta_nuevo is None and detalle.precio_venta:
                precio_venta_nuevo = detalle.precio_venta
            precio_mayoreo_nuevo = precios_mayoreo.get(detalle_id_str)

            campos_a_actualizar = ['precio_compra']
            producto.precio_compra = detalle.precio_unitario  # siempre actualiza costo

            if precio_venta_nuevo is not None:
                try:
                    producto.precio_venta = float(precio_venta_nuevo)
                    campos_a_actualizar.append('precio_venta')
                except (ValueError, TypeError):
                    pass

            if precio_mayoreo_nuevo is not None:
                try:
                    producto.precio_mayoreo = float(precio_mayoreo_nuevo)
                    campos_a_actualizar.append('precio_mayoreo')
                except (ValueError, TypeError):
                    pass

            producto.save(update_fields=campos_a_actualizar)

            # Actualizar inventario (multi-tienda o single-tienda)
            distribuciones = list(detalle.distribuciones.all())
            if distribuciones:
                # Distribuir stock por tienda según DistribucionDetalle
                stock_por_tienda = []
                for dist in distribuciones:
                    inv, _ = Inventario.objects.select_for_update().get_or_create(
                        producto = detalle.producto,
                        tienda   = dist.tienda,
                        defaults = {
                            "stock_actual": 0,
                            "stock_minimo": 0,
                            "stock_maximo": 0,
                        }
                    )
                    inv.stock_actual += dist.cantidad
                    inv.save()
                    dist.cantidad_recibida = dist.cantidad
                    dist.save()
                    MovimientoInventario.objects.create(
                        producto        = detalle.producto,
                        tienda          = dist.tienda,
                        empleado        = empleado_obj,
                        tipo            = "entrada",
                        cantidad        = dist.cantidad,
                        referencia_tipo = "compra",
                        referencia_id   = compra.id,
                        observacion     = (f"Recepción {compra.numero_orden} "
                                          f"→ {dist.tienda.nombre}"),
                    )
                    stock_por_tienda.append(
                        f"{dist.tienda.nombre}: {float(dist.cantidad)}")
                productos_actualizados.append({
                    "producto":          producto.nombre,
                    "es_nuevo":          detalle.nombre_libre != "",
                    "codigo_barras":     producto.codigo_barras,
                    "categoria":         detalle.categoria.nombre
                                         if detalle.categoria else None,
                    "cantidad_recibida": float(detalle.cantidad),
                    "distribucion":      stock_por_tienda,
                    "precio_venta":  float(producto.precio_venta),
                    "precio_compra": float(producto.precio_compra),
                })
            else:
                # Modo legacy: todo va a compra.tienda
                inv, _ = Inventario.objects.select_for_update().get_or_create(
                    producto = detalle.producto,
                    tienda   = compra.tienda,
                    defaults = {
                        "stock_actual": 0,
                        "stock_minimo": 0,
                        "stock_maximo": 0,
                    }
                )
                inv.stock_actual += detalle.cantidad
                inv.save()
                MovimientoInventario.objects.create(
                    producto        = detalle.producto,
                    tienda          = compra.tienda,
                    empleado        = empleado_obj,
                    tipo            = "entrada",
                    cantidad        = detalle.cantidad,
                    referencia_tipo = "compra",
                    referencia_id   = compra.id,
                    observacion     = f"Recepción orden {compra.numero_orden}",
                )
                productos_actualizados.append({
                    "producto":          producto.nombre,
                    "es_nuevo":          detalle.nombre_libre != "",
                    "codigo_barras":     producto.codigo_barras,
                    "categoria":         detalle.categoria.nombre
                                         if detalle.categoria else None,
                    "cantidad_recibida": float(detalle.cantidad),
                    "stock_actual":      float(inv.stock_actual),
                    "precio_venta":  float(producto.precio_venta),
                    "precio_compra": float(producto.precio_compra),
                })

        compra.estado          = "recibida"
        compra.fecha_recepcion = timezone.now()
        compra.save()

        # Registrar gasto contable
        tienda_gasto = compra.tienda
        if tienda_gasto is None:
            # Para compras multi-tienda tomamos la tienda del primer detalle con distribución
            for d in compra.detalles.all():
                primera = d.distribuciones.first()
                if primera:
                    tienda_gasto = primera.tienda
                    break
        if tienda_gasto and compra.total > 0:
            Gasto.objects.create(
                tienda      = tienda_gasto,
                empleado    = empleado_obj,
                categoria   = 'proveedor',
                descripcion = (f'Recepción {compra.numero_orden} — '
                               f'{compra.proveedor.nombre}'),
                monto       = compra.total,
                metodo_pago = 'transferencia',
                visibilidad = 'solo_admin',
            )

        tienda_nombre = compra.tienda.nombre if compra.tienda else "Multi-tienda"
        return Response({
            "detail":    f"Compra {compra.numero_orden} recibida correctamente.",
            "tienda":    tienda_nombre,
            "productos": productos_actualizados,
        })


class CancelarCompraView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            compra = Compra.objects.get(pk=pk) \
                if es_superadmin(request) \
                else Compra.objects.get(
                    pk=pk,
                    proveedor__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response(
                {"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "No se puede cancelar una compra ya recibida."},
                status=400)

        compra.estado = "cancelada"
        compra.save()
        return Response(
            {"detail": f"Compra {compra.numero_orden} cancelada."})


# ── Parseo de facturas de proveedor ──────────────────────────────

class ParsearFacturaView(APIView):
    """
    POST /api/proveedores/compras/parsear-factura/
    Recibe un PDF de factura de proveedor (multipart/form-data, campo 'archivo').
    Extrae el texto con pdfplumber y aplica heurísticas para detectar líneas
    de productos con su cantidad y precio unitario.
    Retorna:
        {
          "productos": [
            {"nombre": str, "cantidad": float, "precio_unitario": float}
          ],
          "texto_crudo": str   (solo en modo debug)
        }
    """
    permission_classes = [EsAdminOSupervisor]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        archivo = request.FILES.get('archivo')
        if not archivo:
            return Response(
                {"error": "Envía el archivo PDF en el campo 'archivo'."},
                status=400)

        extension = archivo.name.lower().split('.')[-1]
        if extension != 'pdf':
            return Response(
                {"error": "Solo se aceptan archivos PDF."},
                status=400)

        try:
            contenido = archivo.read()
            productos = _parsear_pdf(contenido)
        except Exception as e:
            return Response(
                {"error": f"No se pudo leer el PDF: {e}"},
                status=422)

        debug = request.query_params.get('debug') == '1'
        resp = {"productos": productos}
        if debug:
            resp['_debug'] = _debug_pdf(contenido)
        return Response(resp)


def _debug_pdf(contenido: bytes) -> dict:
    """Devuelve info cruda de lo que pdfplumber ve en el PDF."""
    result = {'paginas': []}
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for i, pagina in enumerate(pdf.pages):
            tablas = pagina.extract_tables()
            texto  = pagina.extract_text() or ''
            result['paginas'].append({
                'pagina': i + 1,
                'n_tablas': len(tablas),
                'tablas': [
                    [list(fila) for fila in tabla]
                    for tabla in tablas
                ],
                'texto_primeras_500': texto[:500],
            })
    return result


def _parsear_pdf(contenido: bytes) -> list[dict]:
    """
    Extrae texto de cada página con pdfplumber y busca líneas que se
    parezcan a filas de productos en una factura.

    Estrategia:
    1. Intenta extraer tablas estructuradas (pdfplumber las detecta automáticamente).
    2. Si no hay tablas, cae al modo texto libre con regex.
    """
    productos = []

    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            productos_pagina: list[dict] = []

            # ── Estrategia 1: tablas estructuradas ──────────────
            tablas = pagina.extract_tables()
            for tabla in tablas:
                for fila in tabla:
                    item = _fila_a_producto(fila)
                    if item:
                        productos_pagina.append(item)

            # ── Estrategia 2: texto libre ────────────────────────
            # Se activa cuando las tablas detectadas no contienen productos
            # (p.ej. el PDF tiene tablas de cabecera/totales pero los productos
            # están en texto libre sin bordes visibles)
            if not productos_pagina:
                texto = pagina.extract_text() or ''
                for linea in texto.splitlines():
                    item = _linea_texto_a_producto(linea)
                    if item:
                        productos_pagina.append(item)

            productos.extend(productos_pagina)

    # Deduplica por (nombre + precio) — permite mismo nombre con precios distintos
    vistos = set()
    result = []
    for p in productos:
        key = (p['nombre'].lower().strip(), round(p['precio_unitario'], 2))
        if key not in vistos:
            vistos.add(key)
            result.append(p)

    return result


# ── Constantes del parser ─────────────────────────────────────────────────────

# Palabras en encabezados/totales que NO son nombres de producto
_SKIP_HEADERS = {
    # español
    'descripcion', 'descripción', 'producto', 'productos',
    'articulo', 'artículo', 'articulos', 'artículos',
    'concepto', 'item', 'items', 'detalle', 'detalles',
    'cantidad', 'cant', 'cant.', 'cantidades',
    'precio', 'precio unit', 'precio unitario',
    'valor', 'vr', 'vr.', 'valor unit', 'valor unitario',
    'vr. unit.', 'vr unit.', 'vr.unit', 'vr.unit.',
    'subtotal', 'sub-total', 'sub total',
    'total', 'gran total', 'total general',
    'total cantidad', 'total cantidades',
    'unitario', 'p.u.', 'pu', 'p/u',
    'codigo', 'código', 'cod', 'cod.', 'ref', 'ref.', '#', 'no', 'no.',
    'dscto', 'dscto.', 'descuento', 'desc', 'desc.', 'dto', 'dto.',
    'iva', 'igv', 'itbis', 'impuesto', 'imp', 'imp.',
    'unidad', 'und', 'und.', 'unidades', 'um', 'u.m.',
    'presentacion', 'presentación', 'empaque',
    'neto', 'bruto', 'efectivo', 'banco', 'cambio', 'abono', 'saldo',
    'vr descuento', 'vr impuesto',
    'pagina', 'página', 'page', 'observacion', 'observación',
    'vendedor', 'cliente', 'nombre', 'ciudad', 'dirección', 'direccion',
    'telefono', 'teléfono', 'correo', 'contacto', 'plazo',
    # english
    'description', 'qty', 'quantity', 'price', 'unit price',
    'amount', 'discount', 'tax', 'vat', 'subtotal',
    'total amount', 'line total', 'extended', 'ext.',
    'product', 'code', 'sku', 'uom', 'unit',
}

# Palabras que identifican filas de resumen/total (descarta la fila completa)
_PALABRAS_TOTAL = {
    'total', 'subtotal', 'sub-total', 'sub total', 'gran total',
    'neto', 'bruto', 'efectivo', 'banco', 'cambio', 'abono', 'saldo',
    'descuento', 'iva', 'impuesto', 'igv', 'itbis',
    'total cantidad', 'vr descuento', 'vr impuesto',
}

# Celda puramente numérica/porcentual → no es un nombre de producto
_RE_SOLO_NUM = re.compile(r'^[\d.,\s%+\-/x×*()]+$')

# Código de referencia: varios formatos comunes
_RE_CODIGO_REF = re.compile(
    r'^[A-Z]{1,8}[-_./][\w]{2,}$'       # CRE-2589189, SKU.001, REF/123
    r'|^\d{4,}[-_/]\w+$'                 # 12345-001
    r'|^[A-Z]\d{4,}$'                    # A12345
    r'|^[A-Z]{2,}\d{3,}$',              # ABC1234
    re.IGNORECASE,
)

# Sufijos de unidad y moneda a eliminar antes de parsear números
_RE_STRIP_PREFIJO  = re.compile(
    r'^(?:GTQ|COP|MXN|USD|CLP|PEN|HNL|NIO|CRC|DOP|PYG|UYU|ARS|BOB|PAB'
    r'|Col\.?\$?|Q\.?|US\$?|\$|€|£|₡|¥|₹|Bs\.?)\s*',
    re.IGNORECASE,
)
_RE_STRIP_SUFIJO   = re.compile(
    # \s* permite espacio opcional; NO requiere \b al inicio para capturar "2und." además de "2 und."
    # (?=\s*$) garantiza que la unidad sea lo ÚLTIMO en la celda → sin falsos positivos
    r'\s*(?:und\.?|pcs?\.?|pzas?\.?|kg\.?|gr?\.?|lts?\.?|mls?\.?'
    r'|mts?\.?|cm\.?|m2|m3|caja|cajas|par|pares|rollo|rollos'
    r'|bolsa|bolsas|saco|sacos|bulto|bultos|dz|docenas?|pack|pqt\.?'
    r'|u\.)(?=\s*$)',
    re.IGNORECASE,
)


# ── Función central de limpieza numérica ──────────────────────────────────────

def _limpiar_numero(texto: str) -> float | None:
    """
    Parsea un número en cualquier formato regional a float:
      10.500      → 10500   (miles colombiano/europeo)
      10,500      → 10500   (miles americano)
      10.500,50   → 10500.5 (europeo con decimal)
      10,500.50   → 10500.5 (americano con decimal)
      10,5        → 10.5    (decimal europeo sin miles)
      10.5        → 10.5    (decimal americano sin miles)
      Q10.500     → 10500   (con símbolo de moneda)
      2 und.      → 2       (con unidad)
      0,0 %       → 0       (porcentaje)
    """
    s = (texto or '').strip()

    # Quitar prefijos de moneda y sufijos de unidad
    s = _RE_STRIP_PREFIJO.sub('', s)
    s = _RE_STRIP_SUFIJO.sub('', s).strip()
    # Quitar %, espacios internos residuales y signos
    s = re.sub(r'[%\s]', '', s)

    if not s:
        return None

    tiene_punto = '.' in s
    tiene_coma  = ',' in s

    if tiene_punto and tiene_coma:
        # Formato mixto: el separador que aparece ÚLTIMO es el decimal
        if s.rindex('.') > s.rindex(','):
            # US: 1,250.50 — eliminar comas
            s = s.replace(',', '')
        else:
            # Europeo: 1.250,50 — eliminar puntos, coma → punto
            s = s.replace('.', '').replace(',', '.')

    elif tiene_coma and not tiene_punto:
        # Solo coma: ¿decimal europeo (10,50) o miles US (10,500)?
        partes = s.split(',')
        if len(partes) == 2 and len(partes[-1]) <= 2:
            # 10,5 / 10,50 → decimal
            s = s.replace(',', '.')
        else:
            # 10,500 / 1,250,000 → miles
            s = s.replace(',', '')

    elif tiene_punto and not tiene_coma:
        # Solo punto: ¿miles colombiano (10.500) o decimal (10.5)?
        if re.fullmatch(r'\d{1,3}(\.\d{3})+', s):
            # Exactamente grupos de 3 → separador de miles
            s = s.replace('.', '')
        # else: decimal normal (10.5) o entero con punto (no common, dejar)

    try:
        return float(s)
    except ValueError:
        return None


# ── Algoritmo de matching cantidad-precio-subtotal ────────────────────────────

def _match_cant_precio(numeros: list[float]) -> tuple[float, float] | None:
    """
    Busca la pareja (cantidad, precio_unitario) en una lista de números
    de una fila de factura, usando el subtotal como validación.

    Estrategia en 2 pasadas:
    1. Match exacto: cant × precio ≈ subtotal  (±5%)
    2. Match con descuento: cant × precio > subtotal  (hasta 50% de descuento)

    Esto permite saltar la columna de nro. de ítem automáticamente.
    """
    n = len(numeros)
    if n < 2:
        return None

    # Pasada 1: match directo (sin descuento o descuento ya aplicado)
    if n >= 3:
        for i in range(n):
            for j in range(i + 1, n):
                c, pu = numeros[i], numeros[j]
                if c <= 0 or pu <= 0:
                    continue
                for k in range(j + 1, n):
                    sub = numeros[k]
                    if sub <= 0:
                        continue
                    ratio = abs(c * pu - sub) / max(sub, 0.01)
                    if ratio < 0.06:          # ±6% para redondeos de moneda
                        return (c, pu)

    # Pasada 2: tolerar descuento de hasta 50%
    if n >= 3:
        for i in range(n):
            for j in range(i + 1, n):
                c, pu = numeros[i], numeros[j]
                if c <= 0 or pu <= 0:
                    continue
                esperado = c * pu
                for k in range(j + 1, n):
                    sub = numeros[k]
                    if sub <= 0:
                        continue
                    if esperado > sub:
                        disc = (esperado - sub) / esperado
                        if disc <= 0.50:
                            return (c, pu)

    # Fallback: usar los dos primeros números positivos
    positivos = [n for n in numeros if n > 0]
    if len(positivos) >= 2:
        return (positivos[0], positivos[1])
    if len(positivos) == 1:
        return (positivos[0], 0.0)

    return None


# ── Parser de filas de tabla ──────────────────────────────────────────────────

def _candidatos_nombre(celdas: list[str]) -> list[str]:
    """
    Devuelve celdas que podrían contener el nombre del producto.
    Excluye: celdas cortas, encabezados conocidos, celdas puramente numéricas.
    """
    result = []
    for c in celdas:
        if not c or len(c) < 2:
            continue
        cl = c.lower().strip()
        if cl in _SKIP_HEADERS:
            continue
        # Celda es solo números/porcentajes/operadores
        if _RE_SOLO_NUM.match(c):
            continue
        # Celda que empieza con número y tiene solo dígitos y separadores (ej: "10.500")
        if _limpiar_numero(c) is not None and not re.search(r'[a-záéíóúüñA-Z]', c):
            continue
        result.append(c)
    return result


def _es_fila_total(celdas: list[str]) -> bool:
    """True si la fila parece ser una línea de total/resumen, no un producto."""
    for c in celdas:
        cl = (c or '').lower().strip()
        if cl in _PALABRAS_TOTAL:
            return True
        # "Total: 230.000" o "Vr Descuento: 0"
        if re.match(r'^(?:total|subtotal|descuento|iva|impuesto)\b', cl):
            return True
    return False


def _fila_a_producto(fila: list) -> dict | None:
    """Interpreta una fila de tabla pdfplumber como un producto de factura."""
    if not fila:
        return None

    celdas = [str(c or '').strip() for c in fila]

    # Descarta filas de total/resumen
    if _es_fila_total(celdas):
        return None

    candidatos = _candidatos_nombre(celdas)
    if not candidatos:
        return None

    # Clasifica candidatos: con espacio (descripción) vs código vs texto simple
    con_espacio = [c for c in candidatos if ' ' in c]
    codigos     = [c for c in candidatos if _RE_CODIGO_REF.match(c)]
    sin_espacio = [c for c in candidatos
                   if ' ' not in c and not _RE_CODIGO_REF.match(c)]

    if con_espacio:
        descripcion = max(con_espacio, key=len)
    elif sin_espacio:
        descripcion = max(sin_espacio, key=len)
    else:
        descripcion = None

    # Combinar descripción + código para nombres únicos
    # "PULSERA F (CRE-2589189)" resuelve el caso de múltiples ítems con mismo nombre
    codigo_ref = codigos[0] if codigos else ''
    if descripcion and codigo_ref:
        nombre = f"{descripcion} ({codigo_ref})"
    elif descripcion:
        nombre = descripcion
    elif codigo_ref:
        nombre = codigo_ref
    else:
        return None

    if nombre.lower().strip() in _SKIP_HEADERS:
        return None

    # Extraer todos los valores numéricos de la fila
    numeros = [n for c in celdas if (n := _limpiar_numero(c)) is not None and n > 0]

    match = _match_cant_precio(numeros)
    if match is None:
        return None

    cantidad, precio_unitario = match

    # Descarta filas de resumen que se colaron (ej: "Total Cantidad: 22")
    if precio_unitario == 0 and cantidad > 50_000:
        return None

    return {
        'nombre':          nombre,
        'cantidad':        cantidad,
        'precio_unitario': precio_unitario,
    }


# ── Parser de texto libre (fallback cuando no hay tabla) ─────────────────────

def _linea_texto_a_producto(linea: str) -> dict | None:
    """
    Extrae un producto de una línea de texto libre cuando pdfplumber
    no detectó tablas. Tokeniza la línea y aplica la misma lógica de
    matching que el parser de tablas.
    """
    linea = linea.strip()
    if not linea or len(linea) < 5:
        return None

    tokens = linea.split()

    # Saltar número(s) de ítem al inicio: "1 CRE-... NOMBRE 2 10.500 ..."
    # Un número de ítem es un entero pequeño (≤ 4 dígitos) sin separadores
    inicio = 0
    while inicio < len(tokens) and re.fullmatch(r'\d{1,4}', tokens[inicio]):
        inicio += 1
    tokens = tokens[inicio:]

    # Acumula tokens de texto al inicio hasta encontrar el primer número
    nombre_tokens = []
    resto_tokens  = []
    en_nombre     = True

    for tok in tokens:
        if en_nombre and _limpiar_numero(tok) is None:
            nombre_tokens.append(tok)
        else:
            en_nombre = False
            resto_tokens.append(tok)

    nombre = ' '.join(nombre_tokens).strip()
    if not nombre or len(nombre) < 2:
        return None
    if nombre.lower() in _SKIP_HEADERS:
        return None
    if _es_fila_total([nombre]):
        return None
    # Líneas de metadatos: etiquetas ("Nit:", "Ciudad:") o campos múltiples ("A / B")
    if nombre.endswith(':') or ' / ' in nombre:
        return None

    numeros = [n for t in resto_tokens if (n := _limpiar_numero(t)) is not None and n > 0]

    match = _match_cant_precio(numeros)
    if match is None:
        return None

    cantidad, precio_unitario = match
    return {
        'nombre':          nombre,
        'cantidad':        cantidad,
        'precio_unitario': precio_unitario,
    }


# ── Cuentas por Pagar ─────────────────────────────────────────
class CuentasPagarView(APIView):
    """
    GET /api/proveedores/cuentas-pagar/
    Lista compras a crédito no pagadas, agrupadas por proveedor.
    Parámetros: tienda_id (opcional), vencidas=1 (solo las vencidas).
    """
    permission_classes = [EsAdminOSupervisor]

    def get(self, request):
        from django.utils import timezone as tz

        tienda_id = request.query_params.get("tienda_id")
        solo_vencidas = request.query_params.get("vencidas") == "1"

        qs = Compra.objects.filter(a_credito=True, pagado=False, estado="recibida")
        qs = scope_qs(request, qs, campo_empresa="tienda__empresa", tienda_id=tienda_id)

        if solo_vencidas:
            qs = qs.filter(fecha_vencimiento__lt=tz.now().date())

        hoy = tz.now().date()
        compras = []
        total_deuda = 0.0
        for c in qs.select_related("proveedor", "tienda").order_by("fecha_vencimiento"):
            dias_vencido = (hoy - c.fecha_vencimiento).days if c.fecha_vencimiento else None
            vencida = dias_vencido is not None and dias_vencido > 0
            compras.append({
                "id":               c.id,
                "numero_orden":     c.numero_orden,
                "proveedor_id":     c.proveedor_id,
                "proveedor_nombre": c.proveedor.nombre,
                "tienda_id":        c.tienda_id,
                "tienda_nombre":    c.tienda.nombre,
                "total":            float(c.total),
                "fecha_orden":      c.fecha_orden.date().isoformat(),
                "fecha_vencimiento": c.fecha_vencimiento.isoformat() if c.fecha_vencimiento else None,
                "dias_vencido":     dias_vencido,
                "vencida":          vencida,
            })
            total_deuda += float(c.total)

        return Response({
            "total_deuda": round(total_deuda, 2),
            "cantidad":    len(compras),
            "compras":     compras,
        })


class MarcarPagadaView(APIView):
    """
    PATCH /api/proveedores/compras/<pk>/marcar-pagada/
    Marca una compra a crédito como pagada.
    """
    permission_classes = [EsAdminOSupervisor]

    def patch(self, request, pk):
        if es_superadmin(request):
            compra = Compra.objects.filter(pk=pk).first()
        else:
            empresa = get_empresa(request)
            compra = Compra.objects.filter(pk=pk, proveedor__empresa=empresa).first()
        if not compra:
            return Response({"error": "Compra no encontrada."}, status=404)

        if not compra.a_credito:
            return Response({"error": "Esta compra no es a crédito."}, status=400)

        compra.pagado = True
        compra.save(update_fields=["pagado"])
        return Response({"id": compra.id, "pagado": True})
