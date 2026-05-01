# productos/views.py

from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q, F, Sum
from decimal import Decimal

from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa
from .models import (Categoria, Producto, Inventario, MovimientoInventario, generar_codigo_barras_interno)
from .serializers import (
    CategoriaSerializer, ProductoSerializer, ProductoSimpleSerializer,
    InventarioSerializer, AjusteInventarioSerializer,
    MovimientoInventarioSerializer, ImportarProductoItemSerializer
)


# ── Helper categoría ──────────────────────────────────────
def _resolver_categoria(raw_nombre: str, empresa):
    nombre = ' '.join((raw_nombre or '').split())
    if not nombre:
        return None
    categoria = Categoria.objects.filter(
        nombre__iexact=nombre, empresa=empresa
    ).first()
    if not categoria:
        categoria = Categoria.objects.create(
            nombre=nombre, empresa=empresa)
    return categoria


# ── Categorías ────────────────────────────────────────────
class CategoriaListCreateView(generics.ListCreateAPIView):
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            qs = Categoria.objects.all()
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
            return qs.order_by("nombre")
        return Categoria.objects.filter(
            empresa=get_empresa(self.request)
        ).order_by("nombre")

    def perform_create(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa")
            if not empresa_id:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "El superadmin debe especificar una empresa.")
            serializer.save()
        else:
            serializer.save(empresa=get_empresa(self.request))


class CategoriaDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Categoria.objects.all()
        return Categoria.objects.filter(
            empresa=get_empresa(self.request))


# ── Productos ─────────────────────────────────────────────
class ProductoListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductoSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [EsAdminOSupervisor()]

    def get_queryset(self):
        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            qs = Producto.objects.select_related("categoria")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
        else:
            empresa = get_empresa(self.request)
            qs = Producto.objects.select_related("categoria").filter(
                empresa=empresa)

        activo = self.request.query_params.get("activo", "true")
        if activo == "true":
            qs = qs.filter(activo=True)
        elif activo == "false":
            qs = qs.filter(activo=False)

        categoria = self.request.query_params.get("categoria")
        buscar    = self.request.query_params.get("q")
        tienda_id = self.request.query_params.get("tienda_id")

        if categoria: qs = qs.filter(categoria_id=categoria)
        if buscar:
            qs = qs.filter(
                Q(nombre__icontains=buscar) |
                Q(codigo_barras__icontains=buscar)
            )
        if tienda_id:
            empresa_filter = {} if es_superadmin(self.request) else \
                {"inventarios__tienda__empresa": get_empresa(self.request)}
            qs = qs.filter(
                inventarios__tienda_id=tienda_id,
                **empresa_filter,
            ).distinct()
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        if es_superadmin(self.request):
            empresa_id = self.request.data.get("empresa")
            if not empresa_id:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "El superadmin debe especificar una empresa.")
            from empresas.models import Empresa
            empresa = Empresa.objects.get(id=empresa_id)
        else:
            empresa = get_empresa(self.request)

        categoria = _resolver_categoria(
            self.request.data.get('categoria_nombre', ''), empresa)
        producto = serializer.save(empresa=empresa, categoria=categoria)

        tienda_id    = self.request.data.get('tienda_id')
        stock_actual = self.request.data.get('stock_actual', 0)
        stock_minimo = self.request.data.get('stock_minimo', 0)
        stock_maximo = self.request.data.get('stock_maximo', 0)

        if tienda_id:
            from tiendas.models import Tienda
            if not Tienda.objects.filter(
                    id=tienda_id, empresa=empresa).exists():
                from rest_framework import serializers
                raise serializers.ValidationError(
                    {"tienda_id": "La tienda no pertenece a esta empresa."})
            Inventario.objects.update_or_create(
                producto=producto, tienda_id=tienda_id,
                defaults={
                    'stock_actual': Decimal(str(stock_actual)),
                    'stock_minimo': Decimal(str(stock_minimo)),
                    'stock_maximo': Decimal(str(stock_maximo)),
                }
            )


class ProductoDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProductoSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Producto.objects.all()
        return Producto.objects.filter(
            empresa=get_empresa(self.request))

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        producto = self.get_object()
        extra    = {}

        if es_superadmin(request):
            from empresas.models import Empresa
            empresa = producto.empresa
        else:
            empresa = get_empresa(request)

        raw_cat = request.data.get('categoria_nombre', '')
        if raw_cat:
            extra['categoria'] = _resolver_categoria(raw_cat, empresa)

        serializer = self.get_serializer(
            producto, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        producto = serializer.save(**extra)

        tienda_id    = request.data.get('tienda_id')
        stock_actual = request.data.get('stock_actual')
        stock_minimo = request.data.get('stock_minimo')
        stock_maximo = request.data.get('stock_maximo')

        if tienda_id:
            from tiendas.models import Tienda
            if not Tienda.objects.filter(
                    id=tienda_id, empresa=empresa).exists():
                return Response(
                    {"tienda_id": "La tienda no pertenece a esta empresa."},
                    status=status.HTTP_403_FORBIDDEN)

            defaults = {}
            if stock_actual is not None:
                defaults['stock_actual'] = Decimal(str(stock_actual))
            if stock_minimo is not None:
                defaults['stock_minimo'] = Decimal(str(stock_minimo))
            if stock_maximo is not None:
                defaults['stock_maximo'] = Decimal(str(stock_maximo))
            if defaults:
                Inventario.objects.update_or_create(
                    producto=producto,
                    tienda_id=tienda_id,
                    defaults=defaults)

        return Response(
            self.get_serializer(producto).data,
            status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        producto = self.get_object()
        producto.activo = False
        producto.save(update_fields=["activo"])
        return Response(
            {"detail": f"Producto '{producto.nombre}' desactivado."},
            status=status.HTTP_200_OK)


# ── Reactivar producto ────────────────────────────────────
class ReactivarProductoView(APIView):
    permission_classes = [EsAdmin]

    def patch(self, request, pk):
        try:
            producto = Producto.objects.get(pk=pk) if es_superadmin(request) \
                else Producto.objects.get(
                    pk=pk, empresa=get_empresa(request))
        except Producto.DoesNotExist:
            return Response(
                {"error": "Producto no encontrado."},
                status=status.HTTP_404_NOT_FOUND)

        if producto.activo:
            return Response(
                {"error": "El producto ya está activo."},
                status=status.HTTP_400_BAD_REQUEST)

        producto.activo = True
        producto.save(update_fields=["activo"])
        return Response({
            "detail": f"Producto '{producto.nombre}' reactivado. ✅",
            "id":     producto.id,
            "nombre": producto.nombre,
            "activo": producto.activo,
        })


# ── Búsqueda POS ──────────────────────────────────────────
class BuscarProductoPOSView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q         = request.query_params.get("q", "").strip()
        tienda_id = request.query_params.get("tienda_id")

        if not q:
            return Response(
                {"error": "Ingresa un término de búsqueda."}, status=400)

        if es_superadmin(request):
            productos = Producto.objects.filter(
                Q(codigo_barras=q) | Q(nombre__icontains=q),
                activo=True,
            )[:10]
        else:
            empresa   = get_empresa(request)
            productos = Producto.objects.filter(
                Q(codigo_barras=q) | Q(nombre__icontains=q),
                activo=True,
                empresa=empresa,
            )[:10]

        data = []
        for p in productos:
            item = ProductoSimpleSerializer(
                p, context={"request": request}).data
            if tienda_id:
                filtro = {"producto": p, "tienda_id": tienda_id}
                if not es_superadmin(request):
                    filtro["tienda__empresa"] = get_empresa(request)
                inv = Inventario.objects.filter(**filtro).first()
                item["stock_actual"] = float(inv.stock_actual) if inv else 0
                item["alerta_stock"] = (
                    "agotado" if not inv or inv.stock_actual <= 0
                    else "bajo" if inv.stock_actual <= inv.stock_minimo
                    else "ok"
                )
            data.append(item)
        return Response(data)


# ── Inventario ────────────────────────────────────────────
class InventarioListView(generics.ListAPIView):
    serializer_class   = InventarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Inventario.objects.select_related("producto", "tienda")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

        tienda_id = self.request.query_params.get("tienda_id")
        alerta    = self.request.query_params.get("alerta")
        activo    = self.request.query_params.get("activo", "true")

        if activo == "true":  qs = qs.filter(producto__activo=True)
        elif activo == "false": qs = qs.filter(producto__activo=False)
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if alerta == "bajo":
            qs = qs.filter(
                stock_actual__lte=F("stock_minimo"), stock_actual__gt=0)
        elif alerta == "agotado":
            qs = qs.filter(stock_actual__lte=0)

        return qs


# ── Ajuste de inventario ──────────────────────────────────
class AjustarInventarioView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, producto_id, tienda_id):
        serializer = AjusteInventarioSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        try:
            filtro = {"producto_id": producto_id, "tienda_id": tienda_id}
            if not es_superadmin(request):
                filtro["tienda__empresa"] = get_empresa(request)
            inv = Inventario.objects.select_for_update().get(**filtro)
        except Inventario.DoesNotExist:
            return Response(
                {"error": "Producto no existe en esta tienda."}, status=404)

        tipo        = serializer.validated_data["tipo"]
        cantidad    = serializer.validated_data["cantidad"]
        observacion = serializer.validated_data.get("observacion", "")

        if tipo == "entrada":
            inv.stock_actual += cantidad
        elif tipo == "salida":
            if inv.stock_actual < cantidad:
                return Response(
                    {"error": "Stock insuficiente."}, status=400)
            inv.stock_actual -= cantidad
        elif tipo == "ajuste":
            inv.stock_actual = cantidad

        inv.save()

        MovimientoInventario.objects.create(
            producto_id=producto_id, tienda_id=tienda_id,
            empleado=request.user, tipo=tipo, cantidad=cantidad,
            referencia_tipo="manual", observacion=observacion,
        )

        return Response({
            "detail":       "Stock actualizado correctamente.",
            "stock_actual": float(inv.stock_actual),
            "tipo":         tipo,
        })


# ── Movimientos de producto ───────────────────────────────
class MovimientosProductoView(generics.ListAPIView):
    serializer_class   = MovimientoInventarioSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        filtro = {
            "producto_id": self.kwargs["producto_id"],
            "tienda_id":   self.kwargs["tienda_id"],
        }
        if not es_superadmin(self.request):
            filtro["tienda__empresa"] = get_empresa(self.request)
        return MovimientoInventario.objects.filter(
            **filtro
        ).select_related("producto", "empleado").order_by("-created_at")


# ── Top productos ─────────────────────────────────────────
class TopProductosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ventas.models import DetalleVenta

        tienda_id = request.query_params.get('tienda_id')
        fecha_ini = request.query_params.get('fecha_ini')
        fecha_fin = request.query_params.get('fecha_fin')
        limite    = int(request.query_params.get('limite', 20))

        qs = DetalleVenta.objects.filter(venta__estado='completada')

        if es_superadmin(request):
            empresa_id = request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(venta__tienda__empresa_id=empresa_id)
        else:
            empresa = get_empresa(request)
            qs = qs.filter(venta__tienda__empresa=empresa)

        if request.user.rol == 'cajero':
            qs = qs.filter(venta__tienda_id=request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(venta__tienda_id=tienda_id)

        if fecha_ini: qs = qs.filter(venta__created_at__date__gte=fecha_ini)
        if fecha_fin: qs = qs.filter(venta__created_at__date__lte=fecha_fin)

        resultado = (
            qs.values('producto__nombre', 'producto__categoria__nombre')
            .annotate(
                total_vendido  = Sum('cantidad'),
                total_ingresos = Sum('subtotal'),
            )
            .order_by('-total_ingresos')[:limite]
        )

        return Response([
            {
                'producto':       r['producto__nombre']            or 'Sin nombre',
                'categoria':      r['producto__categoria__nombre'] or 'Sin categoría',
                'total_vendido':  float(r['total_vendido']  or 0),
                'total_ingresos': float(r['total_ingresos'] or 0),
            }
            for r in resultado
        ])

# ── Importar productos desde Excel (batch) ────────────────
class ImportarProductosView(APIView):
    permission_classes = [EsAdminOSupervisor]

    def post(self, request):
        # Resolver empresa
        if es_superadmin(request):
            empresa_id = request.data.get("empresa")
            if not empresa_id:
                return Response(
                    {"detail": "El superadmin debe especificar una empresa."},
                    status=status.HTTP_400_BAD_REQUEST)
            from empresas.models import Empresa
            try:
                empresa = Empresa.objects.get(id=empresa_id)
            except Empresa.DoesNotExist:
                return Response(
                    {"detail": "Empresa no encontrada."},
                    status=status.HTTP_404_NOT_FOUND)
        else:
            empresa = get_empresa(request)

        # Resolver tienda
        tienda_id = request.data.get("tienda_id")
        tienda    = None
        if tienda_id:
            from tiendas.models import Tienda
            try:
                tienda = Tienda.objects.get(id=tienda_id, empresa=empresa)
            except Tienda.DoesNotExist:
                return Response(
                    {"detail": "La tienda no pertenece a esta empresa."},
                    status=status.HTTP_400_BAD_REQUEST)

        # Validar lista
        productos_data = request.data.get("productos", [])
        if not isinstance(productos_data, list) or len(productos_data) == 0:
            return Response(
                {"detail": "El campo 'productos' debe ser una lista no vacía."},
                status=status.HTTP_400_BAD_REQUEST)

        # Procesar cada producto con su propio savepoint
        creados    = 0
        fallidos   = 0
        resultados = []

        for i, item in enumerate(productos_data):
            fila = i + 2  # +2 porque fila 1 = encabezados Excel

            # Validar con serializer
            ser = ImportarProductoItemSerializer(data=item)
            if not ser.is_valid():
                fallidos += 1
                resultados.append({
                    "fila":    fila,
                    "nombre":  item.get("nombre", "(vacío)"),
                    "success": False,
                    "error":   str(ser.errors),
                })
                continue

            d = ser.validated_data
            try:
                with transaction.atomic():
                    categoria = _resolver_categoria(
                        d.get("categoria_nombre", ""), empresa)

                    # Código de barras: autogenerar si viene vacío
                    codigo = (d.get("codigo_barras") or "").strip() or None
                    if not codigo:
                        codigo = generar_codigo_barras_interno()

                    producto = Producto.objects.create(
                        empresa         = empresa,
                        categoria       = categoria,
                        nombre          = d["nombre"],
                        descripcion     = d.get("descripcion", ""),
                        codigo_barras   = codigo,
                        precio_compra   = d.get("precio_compra", 0),
                        precio_venta    = d.get("precio_venta",  0),
                        unidad_medida   = "unidad",
                        aplica_impuesto = False,
                    )

                    if tienda:
                        Inventario.objects.update_or_create(
                            producto = producto,
                            tienda   = tienda,
                            defaults = {
                                "stock_actual": d.get("stock_actual", 0),
                                "stock_minimo": d.get("stock_minimo", 0),
                            },
                        )

                creados += 1
                resultados.append({
                    "fila":    fila,
                    "nombre":  d["nombre"],
                    "success": True,
                    "id":      producto.id,
                })

            except Exception as e:
                fallidos += 1
                msg = str(e)
                if "unique" in msg.lower():
                    msg = f"Código de barras '{codigo}' ya existe."
                resultados.append({
                    "fila":    fila,
                    "nombre":  d["nombre"],
                    "success": False,
                    "error":   msg,
                })

        return Response({
            "creados":    creados,
            "fallidos":   fallidos,
            "total":      len(productos_data),
            "resultados": resultados,
        }, status=status.HTTP_207_MULTI_STATUS)