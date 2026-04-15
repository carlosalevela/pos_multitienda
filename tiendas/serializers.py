from rest_framework import serializers
from .models import Tienda


class TiendaSerializer(serializers.ModelSerializer):
    total_empleados = serializers.SerializerMethodField()

    class Meta:
        model  = Tienda
        fields = [
            "id", "nombre", "direccion", "telefono",
            "ciudad", "nit", "activo",
            "empresa",                  # ✅ visible para el frontend
            "total_empleados", "created_at"
        ]
        read_only_fields = ["id", "created_at", "empresa"]  # ✅ no modificable desde el body

    def get_total_empleados(self, obj):
        return obj.empleados.filter(activo=True).count()


class TiendaSimpleSerializer(serializers.ModelSerializer):
    """Versión liviana para dropdowns"""
    class Meta:
        model  = Tienda
        fields = ["id", "nombre", "ciudad"]
        # empresa no se expone en dropdowns — no hace falta