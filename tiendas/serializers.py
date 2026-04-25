from rest_framework import serializers
from .models import Tienda


class TiendaSerializer(serializers.ModelSerializer):
    total_empleados = serializers.SerializerMethodField()
    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)

    class Meta:
        model = Tienda
        fields = [
            "id",
            "nombre",
            "direccion",
            "telefono",
            "ciudad",
            "nit",
            "activo",
            "empresa",
            "empresa_nombre",
            "total_empleados",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "empresa",
            "empresa_nombre",
            "total_empleados",
        ]

    def get_total_empleados(self, obj):
        return obj.empleados.filter(activo=True).count()


class TiendaSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tienda
        fields = ["id", "nombre", "ciudad"]