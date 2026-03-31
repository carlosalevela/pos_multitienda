from rest_framework import serializers
from .models import Proveedor, Compra, DetalleCompra


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = [
            "id", "nombre", "nit", "telefono",
            "email", "direccion", "ciudad",
            "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class ProveedorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = ["id", "nombre", "nit"]


class DetalleCompraSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)

    class Meta:
        model  = DetalleCompra
        fields = [
            "id", "producto", "producto_nombre",
            "cantidad", "precio_unitario", "subtotal"
        ]
        read_only_fields = ["id", "subtotal"]

    def validate(self, attrs):
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs


class CompraSerializer(serializers.ModelSerializer):
    detalles         = DetalleCompraSerializer(many=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    tienda_nombre    = serializers.CharField(source="tienda.nombre",    read_only=True)
    empleado_nombre  = serializers.SerializerMethodField()

    class Meta:
        model  = Compra
        fields = [
            "id", "numero_orden",
            "tienda", "tienda_nombre",
            "proveedor", "proveedor_nombre",
            "empleado", "empleado_nombre",
            "total", "estado",
            "fecha_orden", "fecha_recepcion",
            "observaciones", "detalles"
        ]
        read_only_fields = ["id", "total", "fecha_orden", "empleado"]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        total  = sum(d["cantidad"] * d["precio_unitario"] for d in detalles_data)
        compra = Compra.objects.create(total=total, **validated_data)
        for detalle in detalles_data:
            detalle["subtotal"] = detalle["cantidad"] * detalle["precio_unitario"]
            DetalleCompra.objects.create(compra=compra, **detalle)
        return compra