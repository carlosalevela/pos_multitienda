from rest_framework import serializers
from .models import Devolucion, DetalleDevolucion


class DetalleDevolucionSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(
        source="producto.nombre", read_only=True)

    class Meta:
        model  = DetalleDevolucion
        fields = [
            "id", "producto", "producto_nombre",
            "cantidad", "precio_unitario", "subtotal", "motivo",
        ]
        read_only_fields = ["id", "subtotal"]

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "La cantidad debe ser mayor a 0.")
        return value

    def validate_producto(self, producto):
        """Valida que el producto pertenezca a la empresa."""  # ✅
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El producto no pertenece a tu empresa.")
        return producto

    def validate(self, attrs):
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs


class DevolucionSerializer(serializers.ModelSerializer):
    detalles        = DetalleDevolucionSerializer(many=True)
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(
        source="tienda.nombre", read_only=True)
    venta_numero    = serializers.CharField(
        source="venta.numero_factura", read_only=True)

    class Meta:
        model  = Devolucion
        fields = [
            "id", "venta", "venta_numero",
            "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "total_devuelto", "metodo_devolucion",
            "estado", "observaciones",
            "created_at", "detalles",
        ]
        read_only_fields = [
            "id", "empleado", "tienda",
            "total_devuelto", "estado", "created_at",
        ]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def validate_venta(self, venta):
        """Valida que la venta pertenezca a la empresa del usuario."""  # ✅
        request = self.context.get("request")
        if request and venta.tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La venta no pertenece a tu empresa.")
        if venta.estado == "anulada":
            raise serializers.ValidationError(
                "No se puede devolver una venta anulada.")
        return venta

    def validate_detalles(self, value):
        if not value:
            raise serializers.ValidationError(
                "Debes incluir al menos un producto a devolver.")
        ids = [d["producto"].id for d in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "No puedes repetir el mismo producto en la devolución.")
        return value

    def get_fields(self):
        # ✅ propaga context a los detalles anidados
        fields = super().get_fields()
        fields["detalles"].child.context.update(self.context)
        return fields

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        total = sum(d["subtotal"] for d in detalles_data)
        devolucion = Devolucion.objects.create(
            total_devuelto=total,
            estado="procesada",
            **validated_data,
        )
        DetalleDevolucion.objects.bulk_create([
            DetalleDevolucion(devolucion=devolucion, **d)
            for d in detalles_data
        ])
        return devolucion