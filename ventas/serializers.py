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
            "subtotal", "descuento_total", "impuesto_total",
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

    def validate(self, attrs):
        sesion = attrs.get("sesion_caja")
        if sesion and sesion.estado != "abierta":
            raise serializers.ValidationError("La sesión de caja no está abierta.")
        return attrs

    def create(self, validated_data):
        detalles_data   = validated_data.pop("detalles")
        metodo_pago     = validated_data.get("metodo_pago", "efectivo")
        monto_recibido  = validated_data.get("monto_recibido", Decimal("0"))

        subtotal        = Decimal("0")
        descuento_total = Decimal("0")
        impuesto_total  = Decimal("0")

        for d in detalles_data:
            subtotal        += d["precio_unitario"] * d["cantidad"]
            descuento_total += d.get("descuento", Decimal("0")) * d["cantidad"]
            producto = d["producto"]
            if producto.aplica_impuesto:
                base = (d["precio_unitario"] - d.get("descuento", Decimal("0"))) * d["cantidad"]
                impuesto_total += base * (producto.porcentaje_impuesto / Decimal("100"))

        total  = subtotal - descuento_total + impuesto_total
        vuelto = monto_recibido - total if metodo_pago == "efectivo" else Decimal("0")

        ultimo = Venta.objects.order_by("-id").first()
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