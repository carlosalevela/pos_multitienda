from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Q, F, Sum
from decimal import Decimal

from .models import Categoria, Producto, Inventario, MovimientoInventario
from .serializers import (
    CategoriaSerializer, ProductoSerializer, ProductoSimpleSerializer,
    InventarioSerializer, AjusteInventarioSerializer,
    MovimientoInventarioSerializer,
)


# ── Permisos ────────────────────────────────────────────────

class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Helper empresa ──────────────────────────────────────────

def _get_empresa(request):
    return request.user.empresa


# ── Helper para resolver categoría ─────────────────────────

def _resolver_categoria(raw_nombre: str, empresa):
    """Busca o crea categoría DENTRO de la empresa del usuario."""
    nombre = ' '.join((raw_nombre or '').split())
    if not nombre:
        return None
    categoria = Categoria.objects.filter(
        nombre__iexact=nombre, empresa=empresa   # ✅ scoped
    ).first()
    if not categoria:
        categoria = Categoria.objects.create(nombre=nombre, empresa=empresa)
    return categoria


# ── Categorías ──────────────────────────────────────────────

class CategoriaListCreateView(generics.ListCreateAPIView):
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        # ✅ solo categorías de la empresa del usuario
        return Categoria.objects.filter(
            empresa=_get_empresa(self.request)
        ).order_by("nombre")

    def perform_create(self, serializer):
        serializer.save(empresa=_get_empresa(self.request))  # ✅


class CategoriaDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = CategoriaSerializer
    permission_classes = [EsAdmin]

    def get_queryset(self):
        return Categoria.objects.filter(empresa=_get_empresa(self.request))  # ✅


# ── Productos ───────────────────────────────────────────────

class ProductoListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductoSerializer

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [EsAdminOSupervisor()]

    def get_queryset(self):
        empresa   = _get_empresa(self.request)
        qs        = Producto.objects.select_related("categoria").filter(empresa=empresa)  # ✅
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
            qs = qs.filter(
                Q(nombre__icontains=buscar) |
                Q(codigo_barras__icontains=buscar)
            )
        if tienda_id:
            # ✅ además verifica que la tienda sea de la misma empresa
            qs = qs.filter(
                inventarios__tienda_id=tienda_id,
                inventarios__tienda__empresa=empresa,
            ).distinct()
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        empresa   = _get_empresa(self.request)
        categoria = _resolver_categoria(
            self.request.data.get('categoria_nombre', ''), empresa)  # ✅

        producto = serializer.save(empresa=empresa, categoria=categoria)  # ✅

        tienda_id    = self.request.data.get('tienda_id')
        stock_actual = self.request.data.get('stock_actual', 0)
        stock_minimo = self.request.data.get('stock_minimo', 0)
        stock_maximo = self.request.data.get('stock_maximo', 0)

        if tienda_id:
            # ✅ valida que la tienda sea de la empresa antes de crear inventario
            from tiendas.models import Tienda
            if not Tienda.objects.filter(id=tienda_id, empresa=empresa).exists():
                raise serializers.ValidationError(
                    {"tienda_id": "La tienda no pertenece a tu empresa."})

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
    serializer_class   = ProductoSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        return Producto.objects.filter(empresa=_get_empresa(self.request))  # ✅

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        producto  = self.get_object()
        empresa   = _get_empresa(request)
        extra     = {}
        raw_cat   = request.data.get('categoria_nombre', '')
        if raw_cat:
            extra['categoria'] = _resolver_categoria(raw_cat, empresa)  # ✅

        serializer = self.get_serializer(producto, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        producto = serializer.save(**extra)

        tienda_id    = request.data.get('tienda_id')
        stock_actual = request.data.get('stock_actual')
        stock_minimo = request.data.get('stock_minimo')
        stock_maximo = request.data.get('stock_maximo')

        if tienda_id:
            # ✅ valida tienda de la empresa
            from tiendas.models import Tienda
            if not Tienda.objects.filter(id=tienda_id, empresa=empresa).exists():
                return Response(
                    {"tienda_id": "La tienda no pertenece a tu empresa."},
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
                    producto=producto, tienda_id=tienda_id, defaults=defaults)

        return Response(self.get_serializer(producto).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        producto = self.get_object()
        producto.activo = False
        producto.save(update_fields=["activo"])
        return Response(
            {"detail": f"Producto '{producto.nombre}' desactivado."},
            status=status.HTTP_200_OK)


# ── Reactivar producto ──────────────────────────────────────

class ReactivarProductoView(APIView):
    permission_classes = [EsAdmin]

    def patch(self, request, pk):
        empresa = _get_empresa(request)
        try:
            # ✅ scoped a la empresa — ya no puede tocar productos ajenos
            producto = Producto.objects.get(pk=pk, empresa=empresa)
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


# ── Búsqueda POS ────────────────────────────────────────────

class BuscarProductoPOSView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q         = request.query_params.get("q", "").strip()
        tienda_id = request.query_params.get("tienda_id")
        empresa   = _get_empresa(request)

        if not q:
            return Response({"error": "Ingresa un término de búsqueda."}, status=400)

        productos = Producto.objects.filter(
            Q(codigo_barras=q) | Q(nombre__icontains=q),
            activo=True,
            empresa=empresa,    # ✅
        )[:10]

        data = []
        for p in productos:
            item = ProductoSimpleSerializer(p, context={"request": request}).data
            if tienda_id:
                # ✅ solo consulta inventario de tiendas de la empresa
                inv = Inventario.objects.filter(
                    producto=p,
                    tienda_id=tienda_id,
                    tienda__empresa=empresa,    # ✅
                ).first()
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
        empresa   = _get_empresa(self.request)
        qs        = Inventario.objects.select_related("producto", "tienda").filter(
            tienda__empresa=empresa    # ✅
        )
        tienda_id = self.request.query_params.get("tienda_id")
        alerta    = self.request.query_params.get("alerta")
        activo    = self.request.query_params.get("activo", "true")

        if activo == "true":
            qs = qs.filter(producto__activo=True)
        elif activo == "false":
            qs = qs.filter(producto__activo=False)

        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)
        if alerta == "bajo":
            qs = qs.filter(stock_actual__lte=F("stock_minimo"), stock_actual__gt=0)
        elif alerta == "agotado":
            qs = qs.filter(stock_actual__lte=0)

        return qs


# ── Ajuste de inventario ────────────────────────────────────

class AjustarInventarioView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, producto_id, tienda_id):
        serializer = AjusteInventarioSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        empresa = _get_empresa(request)

        # ✅ verifica que el inventario pertenezca a la empresa
        try:
            inv = Inventario.objects.select_for_update().get(
                producto_id=producto_id,
                tienda_id=tienda_id,
                tienda__empresa=empresa,    # ✅
            )
        except Inventario.DoesNotExist:
            return Response(
                {"error": "Producto no existe en esta tienda."},
                status=404)

        tipo        = serializer.validated_data["tipo"]
        cantidad    = serializer.validated_data["cantidad"]
        observacion = serializer.validated_data.get("observacion", "")

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
            producto_id=producto_id, tienda_id=tienda_id,
            empleado=request.user, tipo=tipo, cantidad=cantidad,
            referencia_tipo="manual", observacion=observacion,
        )

        return Response({
            "detail":       "Stock actualizado correctamente.",
            "stock_actual": float(inv.stock_actual),
            "tipo":         tipo,
        })


# ── Movimientos de producto ─────────────────────────────────

class MovimientosProductoView(generics.ListAPIView):
    serializer_class   = MovimientoInventarioSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        empresa = _get_empresa(self.request)
        return MovimientoInventario.objects.filter(
            producto_id=self.kwargs["producto_id"],
            tienda_id=self.kwargs["tienda_id"],
            tienda__empresa=empresa,    # ✅
        ).select_related("producto", "empleado").order_by("-created_at")


# ── Top productos ───────────────────────────────────────────

class TopProductosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ventas.models import DetalleVenta

        empresa   = _get_empresa(request)
        tienda_id = request.query_params.get('tienda_id')
        fecha_ini = request.query_params.get('fecha_ini')
        fecha_fin = request.query_params.get('fecha_fin')
        limite    = int(request.query_params.get('limite', 20))

        # ✅ base siempre scoped a la empresa
        qs = DetalleVenta.objects.filter(
            venta__estado='completada',
            venta__tienda__empresa=empresa,    # ✅
        )

        if request.user.rol == 'cajero':
            qs = qs.filter(venta__tienda_id=request.user.tienda_id)
        elif tienda_id:
            # ✅ ya no puede pedir tiendas de otras empresas
            qs = qs.filter(venta__tienda_id=tienda_id)

        if fecha_ini:
            qs = qs.filter(venta__created_at__date__gte=fecha_ini)
        if fecha_fin:
            qs = qs.filter(venta__created_at__date__lte=fecha_fin)

        resultado = (
            qs.values('producto__nombre', 'producto__categoria__nombre')
            .annotate(
                total_vendido  = Sum('cantidad'),
                total_ingresos = Sum('subtotal'),
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