from decimal import Decimal
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Sum

from .models import Venta
from .serializers import VentaSerializer
from productos.models import Inventario, MovimientoInventario
from caja.models import SesionCaja
from devoluciones.models import DetalleDevolucion  # ← nuevo import


class EsAdmin(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol == "admin"


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


class CrearVentaView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        tienda_id = request.data.get("tienda")
        sesion    = SesionCaja.objects.filter(tienda_id=tienda_id, estado="abierta").first()

        if not sesion:
            return Response({"error": "No hay caja abierta en esta tienda. Abre la caja primero."}, status=400)

        data = request.data.copy()
        data["sesion_caja"] = sesion.id

        serializer = VentaSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        for item in request.data.get("detalles", []):
            try:
                inv = Inventario.objects.select_for_update().get(
                    producto_id=item["producto"], tienda_id=tienda_id
                )
            except Inventario.DoesNotExist:
                return Response({"error": f"Producto ID {item['producto']} sin inventario en esta tienda."}, status=400)

            if Decimal(str(inv.stock_actual)) < Decimal(str(item["cantidad"])):
                return Response({
                    "error": f"Stock insuficiente para producto ID {item['producto']}. "
                             f"Disponible: {inv.stock_actual}, solicitado: {item['cantidad']}."
                }, status=400)

        venta = serializer.save(empleado=request.user)

        for detalle in venta.detalles.all():
            inv = Inventario.objects.select_for_update().get(producto=detalle.producto, tienda_id=tienda_id)
            inv.stock_actual -= detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto=detalle.producto, tienda_id=tienda_id,
                empleado=request.user, tipo="salida",
                cantidad=detalle.cantidad, referencia_tipo="venta",
                referencia_id=venta.id, observacion=f"Venta {venta.numero_factura}",
            )

        return Response({
            "detail":         "Venta registrada correctamente. ✅",
            "numero_factura": venta.numero_factura,
            "total":          float(venta.total),
            "vuelto":         float(venta.vuelto),
            "metodo_pago":    venta.metodo_pago,
            "cliente":        f"{venta.cliente.nombre} {venta.cliente.apellido}" if venta.cliente else "Consumidor Final",
            "productos_vendidos": [
                {"producto": d.producto.nombre, "cantidad": float(d.cantidad), "subtotal": float(d.subtotal)}
                for d in venta.detalles.all()
            ]
        }, status=201)


class VentaListView(generics.ListAPIView):
    serializer_class   = VentaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs   = Venta.objects.select_related(
            "cliente", "empleado", "tienda", "sesion_caja"
        ).prefetch_related("detalles")
        user = self.request.user

        if user.rol == "cajero":
            qs    = qs.filter(tienda_id=user.tienda_id)
            fecha = self.request.query_params.get("fecha")
            if fecha:
                qs = qs.filter(created_at__date=fecha)
            return qs.order_by("-created_at")

        tienda_id = self.request.query_params.get("tienda_id")
        sesion_id = self.request.query_params.get("sesion_id")
        fecha     = self.request.query_params.get("fecha")
        cliente   = self.request.query_params.get("cliente_id")

        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if sesion_id: qs = qs.filter(sesion_caja_id=sesion_id)
        if fecha:     qs = qs.filter(created_at__date=fecha)
        if cliente:   qs = qs.filter(cliente_id=cliente)

        return qs.order_by("-created_at")


class VentaDetailView(generics.RetrieveAPIView):
    queryset           = Venta.objects.prefetch_related("detalles__producto")
    serializer_class   = VentaSerializer
    permission_classes = [IsAuthenticated]


class AnularVentaView(APIView):
    permission_classes = [EsAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            venta = Venta.objects.prefetch_related("detalles__producto").get(pk=pk)
        except Venta.DoesNotExist:
            return Response({"error": "Venta no encontrada."}, status=404)

        if venta.estado == "anulada":
            return Response({"error": "Esta venta ya está anulada."}, status=400)

        for detalle in venta.detalles.all():
            inv, _ = Inventario.objects.get_or_create(
                producto=detalle.producto, tienda=venta.tienda,
                defaults={"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0}
            )
            inv.stock_actual += detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto=detalle.producto, tienda=venta.tienda,
                empleado=request.user, tipo="entrada",
                cantidad=detalle.cantidad, referencia_tipo="anulacion",
                referencia_id=venta.id, observacion=f"Anulación venta {venta.numero_factura}",
            )

        venta.estado = "anulada"
        venta.save()

        return Response({
            "detail":        f"Venta {venta.numero_factura} anulada. Stock restaurado.",
            "total_anulado": float(venta.total),
        })


# ── Disponibilidad para devolución ────────────────────────────────────────────
class VentaDisponibleDevolucionView(APIView):
    """
    GET /api/ventas/<pk>/disponible-devolucion/
    Devuelve los productos de la venta con cuánto queda disponible para devolver.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            venta = Venta.objects.prefetch_related(
                "detalles__producto"
            ).get(pk=pk)
        except Venta.DoesNotExist:
            return Response(
                {"error": "Venta no encontrada."},
                status=status.HTTP_404_NOT_FOUND)

        if venta.estado == "anulada":
            return Response(
                {"error": "La venta está anulada."},
                status=status.HTTP_400_BAD_REQUEST)

        # Cajero y supervisor solo ven su tienda
        if (request.user.rol in ("supervisor", "cajero")
                and hasattr(request.user, "tienda_id")
                and venta.tienda_id != request.user.tienda_id):
            return Response(
                {"error": "Sin permiso para ver esta venta."},
                status=status.HTTP_403_FORBIDDEN)

        # Cantidades ya devueltas agrupadas por producto
        ya_devuelto = {
            dd["producto_id"]: dd["total"]
            for dd in (
                DetalleDevolucion.objects
                .filter(devolucion__venta=venta, devolucion__estado="procesada")
                .values("producto_id")
                .annotate(total=Sum("cantidad"))
            )
        }

        productos = []
        for d in venta.detalles.all():
            devuelto   = ya_devuelto.get(d.producto_id, Decimal("0"))
            disponible = d.cantidad - devuelto
            if disponible > 0:
                productos.append({
                    "producto_id":      d.producto_id,
                    "producto_nombre":  d.producto.nombre,
                    "precio_unitario":  float(d.precio_unitario),
                    "cantidad_vendida": float(d.cantidad),
                    "ya_devuelta":      float(devuelto),
                    "disponible":       float(disponible),
                })

        return Response({
            "venta_id":        venta.id,
            "numero_factura":  venta.numero_factura,
            "fecha":           venta.created_at.date().isoformat(),
            "total":           float(venta.total),
            "productos":       productos,
            "todos_devueltos": len(productos) == 0,
        })