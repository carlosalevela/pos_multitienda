# compras/views.py

from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone

from core.permissions import EsAdmin, EsAdminOSupervisor, es_superadmin, get_empresa
from .models import Proveedor, Compra
from .serializers import ProveedorSerializer, ProveedorSimpleSerializer, CompraSerializer
from productos.models import Inventario, MovimientoInventario, Producto, generar_codigo_barras_interno
from contabilidad.models import Gasto


# ── Proveedores ───────────────────────────────────────────
class ProveedorListCreateView(generics.ListCreateAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = Proveedor.objects.filter(activo=True)

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
        else:
            qs = qs.filter(empresa=get_empresa(self.request))

        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(nombre__icontains=q)
        return qs.order_by("nombre")

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


class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Proveedor.objects.all()
        return Proveedor.objects.filter(
            empresa=get_empresa(self.request))

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
        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            qs = Proveedor.objects.filter(activo=True)
            if empresa_id:
                qs = qs.filter(empresa_id=empresa_id)
            return qs.order_by("nombre")
        return Proveedor.objects.filter(
            activo=True,
            empresa=get_empresa(self.request),
        ).order_by("nombre")


# ── Compras ───────────────────────────────────────────────
class CompraListCreateView(generics.ListCreateAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = Compra.objects.select_related(
            "proveedor", "tienda", "empleado"
        ).prefetch_related("detalles")

        if es_superadmin(self.request):
            empresa_id = self.request.query_params.get("empresa")
            if empresa_id:
                qs = qs.filter(tienda__empresa_id=empresa_id)
        else:
            qs = qs.filter(tienda__empresa=get_empresa(self.request))

        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if estado:    qs = qs.filter(estado=estado)
        return qs.order_by("-fecha_orden")

    def perform_create(self, serializer):
        empresa = get_empresa(self.request) if not es_superadmin(self.request) \
            else None
        ultimo = Compra.objects.filter(
            tienda__empresa=empresa
        ).order_by("-id").first() if empresa else \
            Compra.objects.order_by("-id").first()

        numero = f"OC-{(ultimo.id + 1 if ultimo else 1):05d}"
        serializer.save(empleado=self.request.user, numero_orden=numero)


class CompraDetailView(generics.RetrieveAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        if es_superadmin(self.request):
            return Compra.objects.prefetch_related("detalles__producto")
        return Compra.objects.filter(
            tienda__empresa=get_empresa(self.request)
        ).prefetch_related("detalles__producto")


class RecibirCompraView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        try:
            qs     = Compra.objects.prefetch_related(
                "detalles__producto", "detalles__categoria")
            compra = qs.get(pk=pk) if es_superadmin(request) \
                else qs.get(pk=pk, tienda__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response({"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "Esta compra ya fue recibida."}, status=400)
        if compra.estado == "cancelada":
            return Response(
                {"error": "No se puede recibir una compra cancelada."}, status=400)

        empresa = compra.tienda.empresa
        productos_actualizados = []

        for detalle in compra.detalles.all():
            if not detalle.producto:
                nuevo_producto = Producto.objects.create(
                    nombre        = detalle.nombre_libre or "Producto sin nombre",
                    categoria     = detalle.categoria,
                    precio_compra = detalle.precio_unitario,
                    precio_venta  = detalle.precio_unitario,
                    codigo_barras = generar_codigo_barras_interno(),
                    empresa       = empresa,
                    activo        = True,
                )
                detalle.producto = nuevo_producto
                detalle.save()

            inv, _ = Inventario.objects.select_for_update().get_or_create(
                producto = detalle.producto,
                tienda   = compra.tienda,
                defaults = {"stock_actual": 0,
                            "stock_minimo": 0, "stock_maximo": 0}
            )
            inv.stock_actual += detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto        = detalle.producto,
                tienda          = compra.tienda,
                empleado        = request.user,
                tipo            = "entrada",
                cantidad        = detalle.cantidad,
                referencia_tipo = "compra",
                referencia_id   = compra.id,
                observacion     = f"Recepción orden {compra.numero_orden}",
            )

            productos_actualizados.append({
                "producto":          detalle.producto.nombre,
                "es_nuevo":          detalle.nombre_libre != "",
                "codigo_barras":     detalle.producto.codigo_barras,
                "categoria":         detalle.categoria.nombre
                                     if detalle.categoria else None,
                "cantidad_recibida": float(detalle.cantidad),
                "stock_actual":      float(inv.stock_actual),
            })

        compra.estado          = "recibida"
        compra.fecha_recepcion = timezone.now()
        compra.save()

        if compra.total > 0:
            Gasto.objects.create(
                tienda      = compra.tienda,
                empleado    = request.user,
                categoria   = 'proveedor',
                descripcion = f'Recepción {compra.numero_orden} — '
                              f'{compra.proveedor.nombre}',
                monto       = compra.total,
                metodo_pago = 'transferencia',
                visibilidad = 'solo_admin',
            )

        return Response({
            "detail":    f"Compra {compra.numero_orden} recibida correctamente.",
            "tienda":    compra.tienda.nombre,
            "productos": productos_actualizados,
        })


class CancelarCompraView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            compra = Compra.objects.get(pk=pk) if es_superadmin(request) \
                else Compra.objects.get(
                    pk=pk, tienda__empresa=get_empresa(request))
        except Compra.DoesNotExist:
            return Response({"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response(
                {"error": "No se puede cancelar una compra ya recibida."},
                status=400)

        compra.estado = "cancelada"
        compra.save()
        return Response(
            {"detail": f"Compra {compra.numero_orden} cancelada."})