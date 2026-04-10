from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import generics, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from productos.models import Inventario, MovimientoInventario
from ventas.models import Venta

from .models import Devolucion, DetalleDevolucion
from .serializers import DevolucionSerializer


# ── Permisos ──────────────────────────────────────────────────────────────────
class PuedeCrearDevolucion(BasePermission):
    """Admin, supervisor y cajero pueden crear/ver devoluciones."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.rol in ("admin", "supervisor", "cajero")
        )

class PuedeCancelarDevolucion(BasePermission):
    """Solo admin o supervisor pueden cancelar devoluciones."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.rol in ("admin", "supervisor")
        )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _restaurar_stock(devolucion: Devolucion, empleado, venta) -> None:
    for detalle in devolucion.detalles.select_related("producto"):
        inv = (
            Inventario.objects
            .select_for_update()
            .filter(producto=detalle.producto, tienda=devolucion.tienda)
            .first()
        )
        if not inv:
            inv = Inventario.objects.create(
                producto=detalle.producto,
                tienda=devolucion.tienda,
                stock_actual=Decimal("0"),
                stock_minimo=Decimal("0"),
                stock_maximo=Decimal("0"),
            )
        inv.stock_actual += detalle.cantidad
        inv.save(update_fields=["stock_actual"])

        MovimientoInventario.objects.create(
            producto=detalle.producto,
            tienda=devolucion.tienda,
            empleado=empleado,
            tipo="entrada",
            cantidad=detalle.cantidad,
            referencia_tipo="devolucion",
            referencia_id=devolucion.id,
            observacion=f"Devolución DEV-{devolucion.id} | {venta.numero_factura}",
        )


def _revertir_stock(devolucion: Devolucion, empleado) -> None:
    for detalle in devolucion.detalles.select_related("producto"):
        inv = (
            Inventario.objects
            .select_for_update()
            .filter(producto=detalle.producto, tienda=devolucion.tienda)
            .first()
        )
        if inv:
            inv.stock_actual = max(
                Decimal("0"), inv.stock_actual - detalle.cantidad)
            inv.save(update_fields=["stock_actual"])

        MovimientoInventario.objects.create(
            producto=detalle.producto,
            tienda=devolucion.tienda,
            empleado=empleado,
            tipo="salida",
            cantidad=detalle.cantidad,
            referencia_tipo="cancelacion_devolucion",
            referencia_id=devolucion.id,
            observacion=f"Cancelación DEV-{devolucion.id}",
        )


# ── Crear devolución ──────────────────────────────────────────────────────────
class CrearDevolucionView(APIView):
    permission_classes = [PuedeCrearDevolucion]   # ✅ cajero incluido

    @transaction.atomic
    def post(self, request):
        venta_id = request.data.get("venta")
        try:
            venta = Venta.objects.prefetch_related("detalles").get(pk=venta_id)
        except (Venta.DoesNotExist, TypeError, ValueError):
            return Response(
                {"error": "Venta no encontrada."},
                status=status.HTTP_404_NOT_FOUND)

        if venta.estado == "anulada":
            return Response(
                {"error": "No se puede devolver una venta anulada."},
                status=status.HTTP_400_BAD_REQUEST)

        # ✅ Supervisor y cajero solo pueden operar su tienda
        if (request.user.rol in ("supervisor", "cajero")
                and hasattr(request.user, "tienda_id")
                and venta.tienda_id != request.user.tienda_id):
            return Response(
                {"error": "No tienes permiso para devolver ventas de otra tienda."},
                status=status.HTTP_403_FORBIDDEN)

        serializer = DevolucionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        vendido = {d.producto_id: d.cantidad for d in venta.detalles.all()}

        ya_devuelto = {
            dd["producto_id"]: dd["total"]
            for dd in (
                DetalleDevolucion.objects
                .filter(devolucion__venta=venta, devolucion__estado="procesada")
                .values("producto_id")
                .annotate(total=Sum("cantidad"))
            )
        }

        for item in request.data.get("detalles", []):
            try:
                prod_id  = int(item.get("producto", 0))
                cantidad = Decimal(str(item.get("cantidad", 0)))
            except (TypeError, ValueError):
                return Response(
                    {"error": "Datos de detalle inválidos."},
                    status=status.HTTP_400_BAD_REQUEST)

            if prod_id not in vendido:
                return Response(
                    {"error": f"Producto ID {prod_id} no pertenece a esta venta."},
                    status=status.HTTP_400_BAD_REQUEST)

            disponible = vendido[prod_id] - ya_devuelto.get(prod_id, Decimal("0"))
            if cantidad > disponible:
                return Response(
                    {
                        "error": (
                            f"Producto ID {prod_id}: solo quedan {disponible} "
                            f"unidades disponibles para devolver "
                            f"(ya devueltas: {ya_devuelto.get(prod_id, 0)})."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST)

        devolucion = serializer.save(empleado=request.user, tienda=venta.tienda)
        _restaurar_stock(devolucion, request.user, venta)

        return Response(
            {
                "detail":          "Devolución procesada correctamente. ✅",
                "devolucion_id":   devolucion.id,
                "venta":           venta.numero_factura,
                "total_devuelto":  float(devolucion.total_devuelto),
                "metodo":          devolucion.metodo_devolucion,
                "productos_devueltos": [
                    {
                        "producto": d.producto.nombre,
                        "cantidad": float(d.cantidad),
                        "subtotal": float(d.subtotal),
                    }
                    for d in devolucion.detalles.select_related("producto")
                ],
            },
            status=status.HTTP_201_CREATED,
        )


# ── Cancelar devolución ───────────────────────────────────────────────────────
class CancelarDevolucionView(APIView):
    permission_classes = [PuedeCancelarDevolucion]  # ✅ cajero excluido

    @transaction.atomic
    def post(self, request, pk):
        try:
            devolucion = (
                Devolucion.objects
                .select_related("venta")
                .prefetch_related("detalles__producto")
                .get(pk=pk)
            )
        except Devolucion.DoesNotExist:
            return Response(
                {"error": "Devolución no encontrada."},
                status=status.HTTP_404_NOT_FOUND)

        # ✅ Supervisor solo puede cancelar devoluciones de su tienda
        if (request.user.rol == "supervisor"
                and hasattr(request.user, "tienda_id")
                and devolucion.tienda_id != request.user.tienda_id):
            return Response(
                {"error": "No tienes permiso para cancelar devoluciones de otra tienda."},
                status=status.HTTP_403_FORBIDDEN)

        if devolucion.estado == "cancelada":
            return Response(
                {"error": "La devolución ya está cancelada."},
                status=status.HTTP_400_BAD_REQUEST)

        _revertir_stock(devolucion, request.user)
        devolucion.estado = "cancelada"
        devolucion.save(update_fields=["estado"])

        return Response(
            {
                "detail":        "Devolución cancelada. El stock fue revertido. ✅",
                "devolucion_id": devolucion.id,
            },
            status=status.HTTP_200_OK,
        )


# ── Listar devoluciones ───────────────────────────────────────────────────────
class DevolucionListView(generics.ListAPIView):
    serializer_class   = DevolucionSerializer
    permission_classes = [PuedeCrearDevolucion]  # ✅ cajero puede ver

    def get_queryset(self):
        qs = (
            Devolucion.objects
            .select_related("venta", "tienda", "empleado")
            .prefetch_related("detalles__producto")
        )
        p = self.request.query_params

        # ✅ Supervisor y cajero ven solo su tienda automáticamente
        if self.request.user.rol in ("supervisor", "cajero"):
            qs = qs.filter(tienda_id=self.request.user.tienda_id)
        elif tienda_id := p.get("tienda_id"):
            qs = qs.filter(tienda_id=tienda_id)

        if estado := p.get("estado"):
            qs = qs.filter(estado=estado)

        if fecha := p.get("fecha"):
            qs = qs.filter(created_at__date=fecha)

        if fecha_ini := p.get("fechaIni"):
            qs = qs.filter(created_at__date__gte=fecha_ini)
        if fecha_fin := p.get("fechaFin"):
            qs = qs.filter(created_at__date__lte=fecha_fin)

        return qs.order_by("-created_at")


# ── Detalle devolución ────────────────────────────────────────────────────────
class DevolucionDetailView(generics.RetrieveAPIView):
    serializer_class   = DevolucionSerializer
    permission_classes = [PuedeCrearDevolucion]  # ✅ cajero puede ver

    def get_queryset(self):
        qs = (
            Devolucion.objects
            .select_related("venta", "tienda", "empleado")
            .prefetch_related("detalles__producto")
        )
        # ✅ Supervisor y cajero no pueden ver detalles de otra tienda
        if self.request.user.rol in ("supervisor", "cajero"):
            qs = qs.filter(tienda_id=self.request.user.tienda_id)
        return qs