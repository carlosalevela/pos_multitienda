from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone

from .models import Proveedor, Compra
from .serializers import ProveedorSerializer, ProveedorSimpleSerializer, CompraSerializer
from productos.models import Inventario, MovimientoInventario,Producto


class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"

class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


# ── Proveedores ───────────────────────────────────────────────
class ProveedorListCreateView(generics.ListCreateAPIView):
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs = Proveedor.objects.filter(activo=True).order_by("nombre")
        q  = self.request.query_params.get("q")
        if q:
            qs = qs.filter(nombre__icontains=q)
        return qs

class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset           = Proveedor.objects.all()
    serializer_class   = ProveedorSerializer
    permission_classes = [EsAdminOSupervisor]

    def destroy(self, request, *args, **kwargs):
        proveedor = self.get_object()
        proveedor.activo = False
        proveedor.save()
        return Response({"detail": f"Proveedor '{proveedor.nombre}' desactivado."})

class ProveedorSimpleListView(generics.ListAPIView):
    queryset           = Proveedor.objects.filter(activo=True).order_by("nombre")
    serializer_class   = ProveedorSimpleSerializer
    permission_classes = [IsAuthenticated]


# ── Compras ───────────────────────────────────────────────────
class CompraListCreateView(generics.ListCreateAPIView):
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs        = Compra.objects.select_related("proveedor", "tienda", "empleado").prefetch_related("detalles")
        tienda_id = self.request.query_params.get("tienda_id")
        estado    = self.request.query_params.get("estado")
        if tienda_id:
            qs = qs.filter(tienda_id=tienda_id)
        if estado:
            qs = qs.filter(estado=estado)
        return qs.order_by("-fecha_orden")

    def perform_create(self, serializer):
        ultimo = Compra.objects.order_by("-id").first()
        numero = f"OC-{(ultimo.id + 1 if ultimo else 1):05d}"
        serializer.save(empleado=self.request.user, numero_orden=numero)

class CompraDetailView(generics.RetrieveAPIView):
    queryset           = Compra.objects.prefetch_related("detalles__producto")
    serializer_class   = CompraSerializer
    permission_classes = [EsAdminOSupervisor]


class RecibirCompraView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request, pk):
        try:
            compra = Compra.objects.prefetch_related(
                "detalles__producto", "detalles__categoria"
            ).get(pk=pk)
        except Compra.DoesNotExist:
            return Response({"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response({"error": "Esta compra ya fue recibida."}, status=400)
        if compra.estado == "cancelada":
            return Response({"error": "No se puede recibir una compra cancelada."}, status=400)

        productos_actualizados = []

        for detalle in compra.detalles.all():

            # ── Producto libre → crear automáticamente ────────
            if not detalle.producto:
                nuevo_producto = Producto.objects.create(
                    nombre        = detalle.nombre_libre or "Producto sin nombre",
                    categoria     = detalle.categoria,       # puede ser null
                    precio_compra = detalle.precio_unitario,
                    precio_venta  = detalle.precio_unitario,
                    activo        = True,
                )
                # Vincula el detalle al nuevo producto para trazabilidad
                detalle.producto = nuevo_producto
                detalle.save()

            # ── Actualizar inventario ─────────────────────────
            inv, _ = Inventario.objects.select_for_update().get_or_create(
                producto = detalle.producto,
                tienda   = compra.tienda,
                defaults = {"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0}
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
                "categoria":         detalle.categoria.nombre if detalle.categoria else None,
                "cantidad_recibida": float(detalle.cantidad),
                "stock_actual":      float(inv.stock_actual),
            })

        compra.estado          = "recibida"
        compra.fecha_recepcion = timezone.now()
        compra.save()

        return Response({
            "detail":    f"Compra {compra.numero_orden} recibida correctamente.",
            "tienda":    compra.tienda.nombre,
            "productos": productos_actualizados,
        })


class CancelarCompraView(APIView):
    permission_classes = [EsAdmin]

    def post(self, request, pk):
        try:
            compra = Compra.objects.get(pk=pk)
        except Compra.DoesNotExist:
            return Response({"error": "Compra no encontrada."}, status=404)

        if compra.estado == "recibida":
            return Response({"error": "No se puede cancelar una compra ya recibida."}, status=400)

        compra.estado = "cancelada"
        compra.save()
        return Response({"detail": f"Compra {compra.numero_orden} cancelada."})