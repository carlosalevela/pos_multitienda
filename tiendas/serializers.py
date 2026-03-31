from rest_framework import serializers
from .models import Tienda
from usuarios.models import Empleado


class TiendaSerializer(serializers.ModelSerializer):
    total_empleados = serializers.SerializerMethodField()

    class Meta:
        model  = Tienda
        fields = [
            "id", "nombre", "direccion", "telefono",
            "ciudad", "nit", "activo",
            "total_empleados", "created_at"
        ]
        read_only_fields = ["id", "created_at"]

    def get_total_empleados(self, obj):
        return obj.empleados.filter(activo=True).count()


class TiendaSimpleSerializer(serializers.ModelSerializer):
    """Versión liviana para dropdowns"""
    class Meta:
        model  = Tienda
        fields = ["id", "nombre", "ciudad"]