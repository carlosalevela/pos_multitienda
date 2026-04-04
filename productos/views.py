from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q, F
from decimal import Decimal
from django.db.models import Sum

from .models import Categoria, Producto, Inventario, MovimientoInventario
from .serializers import (
    CategoriaSerializer, ProductoSerializer, ProductoSimpleSerializer,
    InventarioSerializer, AjusteInventarioSerializer,
    MovimientoInventarioSerializer,
)


class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Categorías ──────────────────────────────────────────────
class CategoriaListCreateView(generics.ListCreateAPIView):
    queryset           = Categoria.objects.all().order_by("nombre")
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdminOSupervisor]


class CategoriaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Categoria.objects.all()
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdmin]


# ── Helper para resolver categoría ─────────────────────────
def _resolver_categoria(raw_nombre: str):
    """
    Normaliza el nombre y busca/crea la categoría.
    ' '.join(raw.split()) colapsa espacios múltiples y caracteres invisibles.
    """
    nombre = ' '.join((raw_nombre or '').split())  # ✅ FIX: espacios normalizados
    if not nombre:
        return None
    categoria = Categoria.objects.filter(nombre__iexact=nombre).first()
    if not categoria:
        categoria = Categoria.objects.create(nombre=nombre)
    return categoria


# ── Productos ───────────────────────────────────────────────
class ProductoListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductoSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [EsAdminOSupervisor()]

    def get_queryset(self):
        qs        = Producto.objects.select_related("categoria").all()
        categoria = self.request.query_params.get("categoria")
        buscar    = self.request.query_params.get("q")
        tienda_id = self.request.query_params.get("tienda_id")
        activo    = self.request.query_params.get("activo", "true")

        if activo == "true":
            qs = qs.filter(activo=True)
        elif activo == "false":
            qs = qs.filter(activo=False)

        if categoria:
            qs = qs.filter(categoria_id=categoria)
        if buscar:
            qs = qs.filter(Q(nombre__icontains=buscar) | Q(codigo_barras__icontains=buscar))
        if tienda_id:
            qs = qs.filter(inventarios__tienda_id=tienda_id).distinct()
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        # ✅ FIX 1: normaliza espacios antes de buscar/crear categoría
        categoria = _resolver_categoria(
            self.request.data.get('categoria_nombre', ''))

        producto = serializer.save(categoria=categoria)

        tienda_id    = self.request.data.get('tienda_id')
        stock_actual = self.request.data.get('stock_actual', 0)
        stock_minimo = self.request.data.get('stock_minimo', 0)
        stock_maximo = self.request.data.get('stock_maximo', 0)

        if tienda_id:
            Inventario.objects.update_or_create(
                producto  = producto,
                tienda_id = tienda_id,
                defaults  = {
                    'stock_actual': Decimal(str(stock_actual)),
                    'stock_minimo': Decimal(str(stock_minimo)),
                    'stock_maximo': Decimal(str(stock_maximo)),
                }
            )


class ProductoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Producto.objects.all()
    serializer_class   = ProductoSerializer
    permission_classes = [EsAdminOSupervisor]

    # ✅ FIX 2: sobreescribir partial_update para manejar categoría y stock
    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        producto = self.get_object()

        # ✅ Resolver categoría con normalización de espacios
        extra = {}
        raw_cat = request.data.get('categoria_nombre', '')
        if raw_cat:
            extra['categoria'] = _resolver_categoria(raw_cat)

        # ✅ Actualizar campos del producto (nombre, precio, etc.)
        serializer = self.get_serializer(producto, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        producto = serializer.save(**extra)

        # ✅ Actualizar stock en Inventario si se envían datos
        tienda_id    = request.data.get('tienda_id')
        stock_actual = request.data.get('stock_actual')
        stock_minimo = request.data.get('stock_minimo')
        stock_maximo = request.data.get('stock_maximo')

        if tienda_id:
            defaults = {}
            if stock_actual is not None:
                defaults['stock_actual'] = Decimal(str(stock_actual))
            if stock_minimo is not None:
                defaults['stock_minimo'] = Decimal(str(stock_minimo))
            if stock_maximo is not None:
                defaults['stock_maximo'] = Decimal(str(stock_maximo))
            if defaults:
                Inventario.objects.update_or_create(
                    producto  = producto,
                    tienda_id = tienda_id,
                    defaults  = defaults,
                )

        return Response(
            self.get_serializer(producto).data,
            status=status.HTTP_200_OK
        )

    def destroy(self, request, *args, **kwargs):
        producto = self.get_object()
        producto.activo = False
        producto.save()
        return Response(
            {"detail": f"Producto '{producto.nombre}' desactivado."},
            status=status.HTTP_200_OK
        )


class BuscarProductoPOSView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q         = request.query_params.get("q", "").strip()
        tienda_id = request.query_params.get("tienda_id")

        if not q:
            return Response({"error": "Ingresa un término de búsqueda."}, status=400)

        productos = Producto.objects.filter(
            Q(codigo_barras=q) | Q(nombre__icontains=q), activo=True
        )[:10]

        data = []
        for p in productos:
            item = ProductoSimpleSerializer(p).data
            if tienda_id:
                inv = Inventario.objects.filter(
                    producto=p, tienda_id=tienda_id).first()
                item["stock_actual"] = float(inv.stock_actual) if inv else 0
                item["alerta_stock"] = (
                    "agotado" if not inv or inv.stock_actual <= 0
                    else "bajo" if inv.stock_actual <= inv.stock_minimo
                    else "ok"
                )
            data.append(item)

        return Response(data)


# ── Inventario ──────────────────────────────────────────────
class InventarioListView(generics.ListAPIView):
    serializer_class   = InventarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs        = Inventario.objects.select_related("producto", "tienda")
        tienda_id = self.request.query_params.get("tienda_id")
        alerta    = self.request.query_params.get("alerta")

        qs = qs.filter(producto__activo=True)

        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)
        if alerta == "bajo":
            qs = qs.filter(stock_actual__lte=F("stock_minimo"), stock_actual__gt=0)
        elif alerta == "agotado":
            qs = qs.filter(stock_actual__lte=0)
        return qs


class AjustarInventarioView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, producto_id, tienda_id):
        serializer = AjusteInventarioSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        tipo        = serializer.validated_data["tipo"]
        cantidad    = serializer.validated_data["cantidad"]
        observacion = serializer.validated_data.get("observacion", "")

        try:
            inv = Inventario.objects.select_for_update().get(
                producto_id=producto_id, tienda_id=tienda_id)
        except Inventario.DoesNotExist:
            return Response(
                {"error": "Producto no existe en esta tienda."}, status=404)

        if tipo == "entrada":
            inv.stock_actual += cantidad
        elif tipo == "salida":
            if inv.stock_actual < cantidad:
                return Response({"error": "Stock insuficiente."}, status=400)
            inv.stock_actual -= cantidad
        elif tipo == "ajuste":
            inv.stock_actual = cantidad

        inv.save()

        MovimientoInventario.objects.create(
            producto_id     = producto_id,
            tienda_id       = tienda_id,
            empleado        = request.user,
            tipo            = tipo,
            cantidad        = cantidad,
            referencia_tipo = "manual",
            observacion     = observacion,
        )

        return Response({
            "detail":       "Stock actualizado correctamente.",
            "stock_actual": float(inv.stock_actual),
            "tipo":         tipo,
        })


class MovimientosProductoView(generics.ListAPIView):
    serializer_class   = MovimientoInventarioSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        return MovimientoInventario.objects.filter(
            producto_id = self.kwargs["producto_id"],
            tienda_id   = self.kwargs["tienda_id"]
        ).select_related("producto", "empleado").order_by("-created_at")
    
class TopProductosView(APIView):
    """
    GET /productos/top-productos/
    Params: tienda_id, fecha_ini, fecha_fin, limite (default 20)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ✅ Import local evita circular import (ventas ↔ productos)
        from ventas.models import DetalleVenta

        tienda_id = request.query_params.get('tienda_id')
        fecha_ini = request.query_params.get('fecha_ini')
        fecha_fin = request.query_params.get('fecha_fin')
        limite    = int(request.query_params.get('limite', 20))

        # ✅ Solo ventas completadas (no anuladas)
        qs = DetalleVenta.objects.filter(venta__estado='completada')

        # ── Restricción por rol ────────────────────────
        if request.user.rol == 'cajero':
            qs = qs.filter(venta__tienda_id=request.user.tienda_id)
        elif tienda_id:
            qs = qs.filter(venta__tienda_id=tienda_id)

        # ── Filtros de fecha ───────────────────────────
        if fecha_ini:
            qs = qs.filter(venta__created_at__date__gte=fecha_ini)
        if fecha_fin:
            qs = qs.filter(venta__created_at__date__lte=fecha_fin)

        # ── Agrupación ─────────────────────────────────
        resultado = (
            qs
            .values(
                'producto__nombre',
                'producto__categoria__nombre',   # ✅ FK Categoria
            )
            .annotate(
                total_vendido  = Sum('cantidad'),   # ✅ campo confirmado
                total_ingresos = Sum('subtotal'),   # ✅ campo confirmado
            )
            .order_by('-total_ingresos')[:limite]
        )

        data = [
            {
                'producto':       r['producto__nombre']            or 'Sin nombre',
                'categoria':      r['producto__categoria__nombre'] or 'Sin categoría',
                'total_vendido':  float(r['total_vendido']  or 0),
                'total_ingresos': float(r['total_ingresos'] or 0),
            }
            for r in resultado
        ]
        return Response(data)