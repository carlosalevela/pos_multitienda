from decimal import Decimal
from rest_framework import serializers
from .models import Venta, DetalleVenta


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
        """Valida que el producto sea de la empresa del usuario."""   # ✅
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El producto no pertenece a tu empresa.")
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
        """Valida que la tienda sea de la empresa del usuario."""     # ✅
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

    def validate_cliente(self, cliente):
        """Valida que el cliente sea de la empresa del usuario."""    # ✅
        if cliente is None:
            return cliente
        request = self.context.get("request")
        if request and cliente.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El cliente no pertenece a tu empresa.")
        return cliente

    def validate_sesion_caja(self, sesion):
        """Valida que la sesión sea de una tienda de la empresa."""   # ✅
        if sesion is None:
            return sesion
        request = self.context.get("request")
        if request and sesion.tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La sesión de caja no pertenece a tu empresa.")
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

        # ✅ numero_factura scoped a empresa — evita FAC-000001 duplicado entre empresas
        empresa = self.context["request"].user.empresa
        ultimo  = Venta.objects.filter(
            tienda__empresa=empresa
        ).order_by("-id").first()
        numero = f"FAC-{(ultimo.id + 1 if ultimo else 1):06d}"

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