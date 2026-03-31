from rest_framework import serializers
from .models import Devolucion, DetalleDevolucion


class DetalleDevolucionSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)

    class Meta:
        model  = DetalleDevolucion
        fields = ["id", "producto", "producto_nombre",
                  "cantidad", "precio_unitario", "subtotal", "motivo"]
        read_only_fields = ["id", "subtotal"]

    def validate(self, attrs):
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs


class DevolucionSerializer(serializers.ModelSerializer):
    detalles        = DetalleDevolucionSerializer(many=True)
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)
    venta_numero    = serializers.CharField(source="venta.numero_factura", read_only=True)

    class Meta:
        model  = Devolucion
        fields = [
            "id", "venta", "venta_numero",
            "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "total_devuelto", "metodo_devolucion",
            "estado", "observaciones",
            "created_at", "detalles"
        ]
        read_only_fields = ["id", "empleado", "total_devuelto", "estado", "created_at"]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        total = sum(d["cantidad"] * d["precio_unitario"] for d in detalles_data)
        devolucion = Devolucion.objects.create(
            total_devuelto=total, estado="procesada", **validated_data
        )
        for d in detalles_data:
            d["subtotal"] = d["cantidad"] * d["precio_unitario"]
            DetalleDevolucion.objects.create(devolucion=devolucion, **d)
        return devolucion