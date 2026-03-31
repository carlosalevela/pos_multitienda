from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction

from .models import Devolucion
from .serializers import DevolucionSerializer
from productos.models import Inventario, MovimientoInventario
from ventas.models import Venta


class EsAdminOSupervisor(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.rol in ["admin", "supervisor"]


class CrearDevolucionView(APIView):
    permission_classes = [EsAdminOSupervisor]

    @transaction.atomic
    def post(self, request):
        venta_id = request.data.get("venta")
        try:
            venta = Venta.objects.prefetch_related("detalles").get(pk=venta_id)
        except Venta.DoesNotExist:
            return Response({"error": "Venta no encontrada."}, status=404)

        if venta.estado == "anulada":
            return Response({"error": "No se puede devolver una venta anulada."}, status=400)

        serializer = DevolucionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        # Validar que los productos pertenecen a la venta
        detalles_venta = {d.producto_id: d.cantidad for d in venta.detalles.all()}
        for item in request.data.get("detalles", []):
            prod_id  = item.get("producto")
            cantidad = float(item.get("cantidad", 0))
            if prod_id not in detalles_venta:
                return Response({"error": f"Producto ID {prod_id} no pertenece a esta venta."}, status=400)
            if cantidad > float(detalles_venta[prod_id]):
                return Response({"error": f"Cantidad a devolver supera la vendida para producto ID {prod_id}."}, status=400)

        devolucion = serializer.save(empleado=request.user, tienda=venta.tienda)

        # Restaurar stock
        for detalle in devolucion.detalles.all():
            inv, _ = Inventario.objects.get_or_create(
                producto=detalle.producto, tienda=venta.tienda,
                defaults={"stock_actual": 0, "stock_minimo": 0, "stock_maximo": 0}
            )
            inv.stock_actual += detalle.cantidad
            inv.save()

            MovimientoInventario.objects.create(
                producto=detalle.producto, tienda=venta.tienda,
                empleado=request.user, tipo="entrada",
                cantidad=detalle.cantidad, referencia_tipo="devolucion",
                referencia_id=devolucion.id,
                observacion=f"Devolución de venta {venta.numero_factura}",
            )

        return Response({
            "detail":         "Devolución procesada correctamente. ✅",
            "devolucion_id":  devolucion.id,
            "venta":          venta.numero_factura,
            "total_devuelto": float(devolucion.total_devuelto),
            "metodo":         devolucion.metodo_devolucion,
            "productos_devueltos": [
                {"producto": d.producto.nombre, "cantidad": float(d.cantidad), "subtotal": float(d.subtotal)}
                for d in devolucion.detalles.all()
            ]
        }, status=201)


class DevolucionListView(generics.ListAPIView):
    serializer_class   = DevolucionSerializer
    permission_classes = [EsAdminOSupervisor]

    def get_queryset(self):
        qs        = Devolucion.objects.select_related("venta","tienda","empleado").prefetch_related("detalles")
        tienda_id = self.request.query_params.get("tienda_id")
        fecha     = self.request.query_params.get("fecha")
        if tienda_id: qs = qs.filter(tienda_id=tienda_id)
        if fecha:     qs = qs.filter(created_at__date=fecha)
        return qs.order_by("-created_at")

class DevolucionDetailView(generics.RetrieveAPIView):
    queryset           = Devolucion.objects.prefetch_related("detalles__producto")
    serializer_class   = DevolucionSerializer
    permission_classes = [EsAdminOSupervisor]