from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import generics, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from productos.models import Inventario, MovimientoInventario, Producto
from ventas.models import Venta

from .models import Devolucion, DetalleDevolucion
from .serializers import DevolucionSerializer


class PuedeCrearDevolucion(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.rol in ("admin", "supervisor", "cajero")


class PuedeCancelarDevolucion(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.rol in ("admin", "supervisor")


def _get_empresa(request):
    return request.user.empresa


def _es_otra_tienda(user, tienda_id) -> bool:
    return user.tienda_id is not None and user.tienda_id != tienda_id


def _restaurar_stock(devolucion: Devolucion, empleado, venta) -> None:
    for detalle in devolucion.detalles.select_related("producto"):
        inv = Inventario.objects.select_for_update().filter(producto=detalle.producto, tienda=devolucion.tienda).first()
        if not inv:
            inv = Inventario.objects.create(producto=detalle.producto, tienda=devolucion.tienda, stock_actual=Decimal("0"), stock_minimo=Decimal("0"), stock_maximo=Decimal("0"))
        inv.stock_actual += detalle.cantidad
        inv.save(update_fields=["stock_actual"])
        MovimientoInventario.objects.create(producto=detalle.producto, tienda=devolucion.tienda, empleado=empleado, tipo="entrada", cantidad=detalle.cantidad, referencia_tipo="devolucion", referencia_id=devolucion.id, observacion=f"Devolución DEV-{devolucion.id} | {venta.numero_factura}")


def _revertir_stock(devolucion: Devolucion, empleado) -> None:
    for detalle in devolucion.detalles.select_related("producto"):
        inv = Inventario.objects.select_for_update().filter(producto=detalle.producto, tienda=devolucion.tienda).first()
        if inv:
            inv.stock_actual = max(Decimal("0"), inv.stock_actual - detalle.cantidad)
            inv.save(update_fields=["stock_actual"])
        MovimientoInventario.objects.create(producto=detalle.producto, tienda=devolucion.tienda, empleado=empleado, tipo="salida", cantidad=detalle.cantidad, referencia_tipo="cancelacion_devolucion", referencia_id=devolucion.id, observacion=f"Cancelación DEV-{devolucion.id}")


class _DevolucionMixin:
    def get_base_queryset(self):
        empresa = _get_empresa(self.request)
        qs = Devolucion.objects.select_related("venta", "tienda", "empleado").prefetch_related("detalles__producto").filter(tienda__empresa=empresa)
        if self.request.user.rol in ("supervisor", "cajero"):
            qs = qs.filter(tienda_id=self.request.user.tienda_id)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class CrearDevolucionView(APIView):
    permission_classes = [PuedeCrearDevolucion]

    @transaction.atomic
    def post(self, request):
        empresa = _get_empresa(request)
        venta_id = request.data.get("venta")
        try:
            venta = Venta.objects.prefetch_related("detalles").get(pk=venta_id, tienda__empresa=empresa)
        except (Venta.DoesNotExist, TypeError, ValueError):
            return Response({"error": "Venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.rol in ("supervisor", "cajero") and _es_otra_tienda(request.user, venta.tienda_id):
            return Response({"error": "No tienes permiso para devolver ventas de otra tienda."}, status=status.HTTP_403_FORBIDDEN)
        serializer = DevolucionSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        vendido = {d.producto_id: d.cantidad for d in venta.detalles.all()}
        ya_devuelto = {dd["producto_id"]: dd["total"] for dd in DetalleDevolucion.objects.filter(devolucion__venta=venta, devolucion__estado="procesada").values("producto_id").annotate(total=Sum("cantidad"))}
        for item in request.data.get("detalles", []):
            try:
                prod_id = int(item.get("producto", 0))
                cantidad = Decimal(str(item.get("cantidad", 0)))
            except (TypeError, ValueError):
                return Response({"error": "Datos de detalle inválidos."}, status=status.HTTP_400_BAD_REQUEST)
            if prod_id not in vendido:
                return Response({"error": f"Producto ID {prod_id} no pertenece a esta venta."}, status=status.HTTP_400_BAD_REQUEST)
            disponible = vendido[prod_id] - ya_devuelto.get(prod_id, Decimal("0"))
            if cantidad > disponible:
                return Response({"error": f"Producto ID {prod_id}: solo quedan {disponible} unidades disponibles para devolver (ya devueltas: {ya_devuelto.get(prod_id, 0)})."}, status=status.HTTP_400_BAD_REQUEST)
        devolucion = serializer.save(empleado=request.user, tienda=venta.tienda)
        _restaurar_stock(devolucion, request.user, venta)
        return Response({"detail": "Devolución procesada correctamente. ✅", "devolucion_id": devolucion.id, "venta": venta.numero_factura, "total_devuelto": float(devolucion.total_devuelto), "metodo": devolucion.metodo_devolucion, "productos_devueltos": [{"producto": d.producto.nombre, "cantidad": float(d.cantidad), "subtotal": float(d.subtotal)} for d in devolucion.detalles.select_related("producto")]}, status=status.HTTP_201_CREATED)


class CambioProductoView(APIView):
    permission_classes = [PuedeCrearDevolucion]

    @transaction.atomic
    def post(self, request):
        empresa = _get_empresa(request)
        venta_id = request.data.get("venta")
        try:
            venta = Venta.objects.prefetch_related("detalles").get(pk=venta_id, tienda__empresa=empresa)
        except (Venta.DoesNotExist, TypeError, ValueError):
            return Response({"error": "Venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.rol in ("supervisor", "cajero") and _es_otra_tienda(request.user, venta.tienda_id):
            return Response({"error": "No tienes permiso para cambiar productos de otra tienda."}, status=status.HTTP_403_FORBIDDEN)
        detalles_data = request.data.get("detalles", [])
        if not detalles_data:
            return Response({"error": "Debes incluir al menos un producto a devolver."}, status=status.HTTP_400_BAD_REQUEST)
        vendido = {d.producto_id: d.cantidad for d in venta.detalles.all()}
        ya_devuelto = {dd["producto_id"]: dd["total"] for dd in DetalleDevolucion.objects.filter(devolucion__venta=venta, devolucion__estado="procesada").values("producto_id").annotate(total=Sum("cantidad"))}
        total_devuelto = Decimal("0")
        for item in detalles_data:
            try:
                prod_id = int(item.get("producto", 0))
                cantidad = Decimal(str(item.get("cantidad", 0)))
                precio_unitario = Decimal(str(item.get("precio_unitario", 0)))
            except (TypeError, ValueError):
                return Response({"error": "Datos de detalle inválidos."}, status=status.HTTP_400_BAD_REQUEST)
            if prod_id not in vendido:
                return Response({"error": f"Producto ID {prod_id} no pertenece a esta venta."}, status=status.HTTP_400_BAD_REQUEST)
            disponible = vendido[prod_id] - ya_devuelto.get(prod_id, Decimal("0"))
            if cantidad > disponible:
                return Response({"error": f"Producto ID {prod_id}: solo quedan {disponible} unidades disponibles para devolver."}, status=status.HTTP_400_BAD_REQUEST)
            total_devuelto += cantidad * precio_unitario
        try:
            producto_reemplazo_id = int(request.data.get("producto_reemplazo"))
            cantidad_reemplazo = Decimal(str(request.data.get("cantidad_reemplazo", 0)))
        except (TypeError, ValueError):
            return Response({"error": "Producto o cantidad de reemplazo inválidos."}, status=status.HTTP_400_BAD_REQUEST)
        if cantidad_reemplazo <= 0:
            return Response({"error": "La cantidad del producto de reemplazo debe ser mayor a 0."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            producto_reemplazo = Producto.objects.get(pk=producto_reemplazo_id, empresa=empresa, activo=True)
        except Producto.DoesNotExist:
            return Response({"error": "Producto de reemplazo no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        inventario_reemplazo = Inventario.objects.select_for_update().filter(producto=producto_reemplazo, tienda=venta.tienda).first()
        if not inventario_reemplazo:
            return Response({"error": "El producto de reemplazo no tiene inventario en esta tienda."}, status=status.HTTP_400_BAD_REQUEST)
        if inventario_reemplazo.stock_actual < cantidad_reemplazo:
            return Response({"error": f"Stock insuficiente para '{producto_reemplazo.nombre}'. Disponible: {inventario_reemplazo.stock_actual}, solicitado: {cantidad_reemplazo}."}, status=status.HTTP_400_BAD_REQUEST)
        total_reemplazo = producto_reemplazo.precio_venta * cantidad_reemplazo
        diferencia = total_reemplazo - total_devuelto
        tipo_diferencia = "cobrar" if diferencia > 0 else "devolver" if diferencia < 0 else "exacto"
        metodo_pago_diferencia = request.data.get("metodo_pago_diferencia", "") or ""
        monto_recibido = request.data.get("monto_recibido", None)
        if monto_recibido in ("", None):
            monto_recibido = None
        else:
            try:
                monto_recibido = Decimal(str(monto_recibido))
            except (TypeError, ValueError):
                return Response({"error": "El monto recibido es inválido."}, status=status.HTTP_400_BAD_REQUEST)
        cambio_entregado = Decimal("0")
        if tipo_diferencia == "cobrar":
            if not metodo_pago_diferencia:
                return Response({"error": "Debes indicar el método de pago de la diferencia."}, status=status.HTTP_400_BAD_REQUEST)
            if monto_recibido is None:
                return Response({"error": "Debes indicar el monto recibido para la diferencia."}, status=status.HTTP_400_BAD_REQUEST)
            if monto_recibido < diferencia:
                return Response({"error": f"El monto recibido no cubre la diferencia de {diferencia}."}, status=status.HTTP_400_BAD_REQUEST)
            if metodo_pago_diferencia == "efectivo":
                cambio_entregado = monto_recibido - diferencia
        serializer = DevolucionSerializer(data={"venta": venta.id, "metodo_devolucion": request.data.get("metodo_devolucion", "efectivo"), "observaciones": request.data.get("observaciones", ""), "detalles": detalles_data}, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        devolucion = serializer.save(empleado=request.user, tienda=venta.tienda, tipo="cambio", producto_reemplazo=producto_reemplazo, cantidad_reemplazo=cantidad_reemplazo, total_reemplazo=total_reemplazo, diferencia=abs(diferencia), tipo_diferencia=tipo_diferencia, metodo_pago_diferencia=metodo_pago_diferencia, monto_recibido=monto_recibido, cambio_entregado=cambio_entregado)
        _restaurar_stock(devolucion, request.user, venta)
        inventario_reemplazo.stock_actual -= cantidad_reemplazo
        inventario_reemplazo.save(update_fields=["stock_actual"])
        MovimientoInventario.objects.create(producto=producto_reemplazo, tienda=venta.tienda, empleado=request.user, tipo="salida", cantidad=cantidad_reemplazo, referencia_tipo="cambio", referencia_id=devolucion.id, observacion=f"Cambio DEV-{devolucion.id} | {venta.numero_factura}")
        return Response({"detail": "Cambio procesado correctamente. ✅", "devolucion_id": devolucion.id, "venta": venta.numero_factura, "tipo": devolucion.tipo, "total_devuelto": float(total_devuelto), "total_reemplazo": float(total_reemplazo), "diferencia": float(abs(diferencia)), "tipo_diferencia": tipo_diferencia, "metodo_pago_diferencia": metodo_pago_diferencia or None, "monto_recibido": float(monto_recibido) if monto_recibido is not None else None, "cambio_entregado": float(cambio_entregado), "producto_reemplazo": {"id": producto_reemplazo.id, "nombre": producto_reemplazo.nombre, "cantidad": float(cantidad_reemplazo), "precio_unitario": float(producto_reemplazo.precio_venta), "total": float(total_reemplazo)}}, status=status.HTTP_201_CREATED)


class CancelarDevolucionView(APIView):
    permission_classes = [PuedeCancelarDevolucion]

    @transaction.atomic
    def post(self, request, pk):
        empresa = _get_empresa(request)
        try:
            devolucion = Devolucion.objects.select_related("venta").prefetch_related("detalles__producto").get(pk=pk, tienda__empresa=empresa)
        except Devolucion.DoesNotExist:
            return Response({"error": "Devolución no encontrada."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.rol == "supervisor" and _es_otra_tienda(request.user, devolucion.tienda_id):
            return Response({"error": "No tienes permiso para cancelar devoluciones de otra tienda."}, status=status.HTTP_403_FORBIDDEN)
        if devolucion.estado == "cancelada":
            return Response({"error": "La devolución ya está cancelada."}, status=status.HTTP_400_BAD_REQUEST)
        _revertir_stock(devolucion, request.user)
        devolucion.estado = "cancelada"
        devolucion.save(update_fields=["estado"])
        return Response({"detail": "Devolución cancelada. El stock fue revertido. ✅", "devolucion_id": devolucion.id}, status=status.HTTP_200_OK)


class DevolucionListView(_DevolucionMixin, generics.ListAPIView):
    serializer_class = DevolucionSerializer
    permission_classes = [PuedeCrearDevolucion]

    def get_queryset(self):
        qs = self.get_base_queryset()
        p = self.request.query_params
        if self.request.user.rol == "admin" and (tienda_id := p.get("tienda_id")):
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


class DevolucionDetailView(_DevolucionMixin, generics.RetrieveAPIView):
    serializer_class = DevolucionSerializer
    permission_classes = [PuedeCrearDevolucion]

    def get_queryset(self):
        return self.get_base_queryset()
