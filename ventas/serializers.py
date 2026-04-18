from decimal import Decimal
from rest_framework import serializers
from django.db import transaction
from .models import Venta, DetalleVenta, PagoVenta
from productos.models import Producto, Inventario, MovimientoInventario
from caja.models import SesionCaja
from clientes.models import Cliente
from devoluciones.models import Devolucion, DetalleDevolucion


class DetalleVentaSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)

    class Meta:
        model  = DetalleVenta
        fields = [
            "id", "producto", "producto_nombre",
            "cantidad", "precio_unitario",
            "descuento", "subtotal"
        ]
        read_only_fields = ["id", "subtotal"]

    def validate_producto(self, producto):
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError("El producto no pertenece a tu empresa.")
        return producto

    def validate(self, attrs):
        precio    = attrs["precio_unitario"]
        cantidad  = attrs["cantidad"]
        descuento = attrs.get("descuento", Decimal("0"))
        attrs["subtotal"] = (precio - descuento) * cantidad
        return attrs


class VentaSerializer(serializers.ModelSerializer):
    detalles        = DetalleVentaSerializer(many=True)
    cliente_nombre  = serializers.SerializerMethodField()
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)

    class Meta:
        model  = Venta
        fields = [
            "id", "numero_factura",
            "tienda", "tienda_nombre",
            "sesion_caja", "cliente", "cliente_nombre",
            "empleado", "empleado_nombre",
            "subtotal", "descuento_total", "impuesto_total",
            "total", "metodo_pago",
            "monto_recibido", "vuelto",
            "estado", "observaciones",
            "created_at", "detalles"
        ]
        read_only_fields = [
            "id", "numero_factura", "empleado",
            "subtotal", "impuesto_total",
            "total", "vuelto", "estado", "created_at"
        ]

    def get_cliente_nombre(self, obj):
        if obj.cliente:
            return f"{obj.cliente.nombre} {obj.cliente.apellido}"
        return "Consumidor Final"

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def validate_tienda(self, tienda):
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError("La tienda no pertenece a tu empresa.")
        return tienda

    def validate_cliente(self, cliente):
        if cliente is None:
            return cliente
        request = self.context.get("request")
        if request and cliente.empresa != request.user.empresa:
            raise serializers.ValidationError("El cliente no pertenece a tu empresa.")
        return cliente

    def validate_sesion_caja(self, sesion):
        if sesion is None:
            return sesion
        request = self.context.get("request")
        if request and sesion.tienda.empresa != request.user.empresa:
            raise serializers.ValidationError("La sesión de caja no pertenece a tu empresa.")
        return sesion

    def validate(self, attrs):
        sesion = attrs.get("sesion_caja")
        if sesion and sesion.estado != "abierta":
            raise serializers.ValidationError("La sesión de caja no está abierta.")
        return attrs

    def create(self, validated_data):
        detalles_data    = validated_data.pop("detalles")
        metodo_pago      = validated_data.get("metodo_pago", "efectivo")
        monto_recibido   = validated_data.get("monto_recibido", Decimal("0"))
        descuento_global = validated_data.pop("descuento_total", Decimal("0"))

        subtotal       = Decimal("0")
        descuento_item = Decimal("0")
        impuesto_total = Decimal("0")

        for d in detalles_data:
            subtotal       += d["precio_unitario"] * d["cantidad"]
            descuento_item += d.get("descuento", Decimal("0")) * d["cantidad"]
            producto = d["producto"]
            if producto.aplica_impuesto:
                base = (d["precio_unitario"] - d.get("descuento", Decimal("0"))) * d["cantidad"]
                impuesto_total += base * (producto.porcentaje_impuesto / Decimal("100"))

        descuento_total = descuento_item + descuento_global
        total  = subtotal - descuento_total + impuesto_total
        vuelto = monto_recibido - total if metodo_pago == "efectivo" else Decimal("0")

        empresa = self.context["request"].user.empresa
        ultimo  = Venta.objects.filter(tienda__empresa=empresa).order_by("-id").first()
        numero  = f"FAC-{(ultimo.id + 1 if ultimo else 1):06d}"

        venta = Venta.objects.create(
            numero_factura  = numero,
            subtotal        = subtotal,
            descuento_total = descuento_total,
            impuesto_total  = impuesto_total,
            total           = total,
            vuelto          = vuelto if vuelto >= 0 else Decimal("0"),
            estado          = "completada",
            **validated_data
        )

        for d in detalles_data:
            DetalleVenta.objects.create(venta=venta, **d)

        return venta


# ─────────────────────────────────────────────────────────────────────────────
# CAMBIO POS
# ─────────────────────────────────────────────────────────────────────────────

class PagoVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PagoVenta
        fields = ["metodo", "monto"]

    def validate_monto(self, value):
        if value <= 0:
            raise serializers.ValidationError("El monto del pago debe ser mayor a 0.")
        return value


class DetalleDevueltoSerializer(serializers.Serializer):
    producto = serializers.PrimaryKeyRelatedField(queryset=Producto.objects.all())
    cantidad = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    def validate_producto(self, producto):
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError("El producto no pertenece a tu empresa.")
        return producto


class CambioPOSSerializer(serializers.Serializer):
    sesion_caja        = serializers.PrimaryKeyRelatedField(queryset=SesionCaja.objects.all())
    cliente            = serializers.PrimaryKeyRelatedField(
                             queryset=Cliente.objects.all(),
                             required=False, allow_null=True, default=None)
    detalles_devueltos = DetalleDevueltoSerializer(many=True, min_length=1)
    productos_nuevos   = DetalleVentaSerializer(many=True, min_length=1)
    pagos              = PagoVentaSerializer(many=True, required=False, default=list)
    observaciones      = serializers.CharField(required=False, allow_blank=True, default="")

    # ── Validaciones de campo ─────────────────────────────────────────────────

    def validate_sesion_caja(self, sesion):
        if sesion.estado != "abierta":
            raise serializers.ValidationError("La sesión de caja no está abierta.")
        request = self.context.get("request")
        if request and sesion.tienda.empresa != request.user.empresa:
            raise serializers.ValidationError("La sesión de caja no pertenece a tu empresa.")
        return sesion

    def validate_cliente(self, cliente):
        if cliente is None:
            return cliente
        request = self.context.get("request")
        if request and cliente.empresa != request.user.empresa:
            raise serializers.ValidationError("El cliente no pertenece a tu empresa.")
        return cliente

    # ── Validación cruzada ────────────────────────────────────────────────────

    def validate(self, attrs):
        total_devuelto = Decimal("0")
        for item in attrs["detalles_devueltos"]:
            total_devuelto += item["producto"].precio_venta * item["cantidad"]

        total_nuevo = Decimal("0")
        for d in attrs["productos_nuevos"]:
            precio    = d["precio_unitario"]
            cantidad  = d["cantidad"]
            descuento = d.get("descuento", Decimal("0"))
            subtotal  = (precio - descuento) * cantidad
            producto  = d["producto"]
            if producto.aplica_impuesto:
                subtotal += subtotal * (producto.porcentaje_impuesto / Decimal("100"))
            total_nuevo += subtotal

        total_pagado_caja = sum(p["monto"] for p in attrs.get("pagos", []))
        saldo_cubierto    = total_devuelto + total_pagado_caja

        if saldo_cubierto < total_nuevo:
            raise serializers.ValidationError({
                "pagos": (
                    f"Saldo insuficiente. "
                    f"Nuevo total: {total_nuevo:.2f}, "
                    f"Reconocido por devolución: {total_devuelto:.2f}, "
                    f"Pagado en caja: {total_pagado_caja:.2f}, "
                    f"Faltante: {(total_nuevo - saldo_cubierto):.2f}."
                )
            })

        attrs["_total_devuelto"]    = total_devuelto
        attrs["_total_nuevo"]       = total_nuevo
        attrs["_total_pagado_caja"] = total_pagado_caja
        return attrs

    # ── Creación atómica ──────────────────────────────────────────────────────

    def create(self, validated_data):
        request       = self.context["request"]
        sesion        = validated_data["sesion_caja"]
        cliente       = validated_data.get("cliente")
        devueltos     = validated_data["detalles_devueltos"]
        nuevos        = validated_data["productos_nuevos"]
        pagos_data    = validated_data.get("pagos", [])
        observaciones = validated_data.get("observaciones", "")
        tienda        = sesion.tienda

        total_devuelto = validated_data["_total_devuelto"]
        total_nuevo    = validated_data["_total_nuevo"]

        with transaction.atomic():

            # ── PASO 1: Número de factura ─────────────────────────────────────
            empresa = request.user.empresa
            ultimo  = Venta.objects.filter(tienda__empresa=empresa).order_by("-id").first()
            numero  = f"FAC-{(ultimo.id + 1 if ultimo else 1):06d}"

            # ── PASO 2: Calcular totales de la nueva venta ────────────────────
            subtotal_venta        = Decimal("0")
            descuento_total_venta = Decimal("0")
            impuesto_total_venta  = Decimal("0")

            for d in nuevos:
                precio    = d["precio_unitario"]
                cantidad  = d["cantidad"]
                descuento = d.get("descuento", Decimal("0"))
                subtotal_venta        += precio * cantidad
                descuento_total_venta += descuento * cantidad
                producto = d["producto"]
                if producto.aplica_impuesto:
                    base = (precio - descuento) * cantidad
                    impuesto_total_venta += base * (producto.porcentaje_impuesto / Decimal("100"))

            # ── PASO 3: Crear Venta ───────────────────────────────────────────
            metodo = (
                "mixto"                      if len(pagos_data) > 1
                else pagos_data[0]["metodo"] if pagos_data
                else "efectivo"
            )
            venta = Venta.objects.create(
                numero_factura  = numero,
                tienda          = tienda,
                sesion_caja     = sesion,
                cliente         = cliente,
                empleado        = request.user,
                subtotal        = subtotal_venta,
                descuento_total = descuento_total_venta,
                impuesto_total  = impuesto_total_venta,
                total           = total_nuevo,
                metodo_pago     = metodo,
                monto_recibido  = sum(p["monto"] for p in pagos_data),
                vuelto          = Decimal("0"),
                estado          = "completada",
                observaciones   = observaciones,
            )

            # ── PASO 4: DetalleVenta y descontar stock ────────────────────────
            for d in nuevos:
                producto = d["producto"]
                cantidad = d["cantidad"]

                DetalleVenta.objects.create(
                    venta           = venta,
                    producto        = producto,
                    cantidad        = cantidad,
                    precio_unitario = d["precio_unitario"],
                    descuento       = d.get("descuento", Decimal("0")),
                    subtotal        = (d["precio_unitario"] - d.get("descuento", Decimal("0"))) * cantidad,
                )

                inv = Inventario.objects.get(producto=producto, tienda=tienda)
                inv.stock_actual -= cantidad
                inv.save(update_fields=["stock_actual"])

                MovimientoInventario.objects.create(
                    producto        = producto,
                    tienda          = tienda,
                    empleado        = request.user,
                    tipo            = "salida",
                    cantidad        = cantidad,
                    referencia_tipo = "cambio_pos",
                    referencia_id   = venta.id,
                    observacion     = "Salida por cambio POS",
                )

            # ── PASO 5: Crear Devolucion (ya existe la venta) ─────────────────
            devolucion = Devolucion.objects.create(
                venta             = venta,           # ✅ ya existe
                tienda            = tienda,
                empleado          = request.user,
                tipo              = "cambio",        # ✅ campo correcto
                total_devuelto    = total_devuelto,  # ✅ campo correcto
                metodo_devolucion = "efectivo",      # ✅ campo requerido
                observaciones     = observaciones,
            )

            # ── PASO 6: DetalleDevolucion y reponer stock ─────────────────────
            for item in devueltos:
                producto = item["producto"]
                cantidad = item["cantidad"]

                DetalleDevolucion.objects.create(
                    devolucion      = devolucion,
                    producto        = producto,
                    cantidad        = cantidad,
                    precio_unitario = producto.precio_venta,
                    subtotal        = producto.precio_venta * cantidad,
                )

                inv = Inventario.objects.get(producto=producto, tienda=tienda)
                inv.stock_actual += cantidad
                inv.save(update_fields=["stock_actual"])

                MovimientoInventario.objects.create(
                    producto        = producto,
                    tienda          = tienda,
                    empleado        = request.user,
                    tipo            = "entrada",
                    cantidad        = cantidad,
                    referencia_tipo = "cambio_pos",
                    referencia_id   = devolucion.id,
                    observacion     = "Reposición por cambio POS",
                )

            # ── PASO 7: PagoVenta ─────────────────────────────────────────────
            PagoVenta.objects.create(venta=venta, metodo="devolucion", monto=total_devuelto)
            for p in pagos_data:
                PagoVenta.objects.create(venta=venta, metodo=p["metodo"], monto=p["monto"])

        return venta
