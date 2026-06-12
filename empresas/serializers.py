# empresas/serializers.py

from rest_framework import serializers
from .models import Empresa


class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Empresa
        fields = [
            'id', 'nombre', 'nit', 'email',
            'telefono', 'direccion', 'ciudad',
            'logo', 'activo', 'created_at',
            # ✅ Configuración mayoreo
            'maneja_mayoreo',
            'cantidad_mayoreo',
        ]
        read_only_fields = ['id', 'created_at']


class EmpresaConfigMayoreoSerializer(serializers.ModelSerializer):
    """
    Serializer ligero solo para leer/actualizar
    la configuración de mayoreo desde Flutter.
    """
    class Meta:
        model  = Empresa
        fields = [
            'id',
            'maneja_mayoreo',
            'cantidad_mayoreo',
        ]
        read_only_fields = ['id']

    def validate_cantidad_mayoreo(self, value):
        if value < 2:
            raise serializers.ValidationError(
                "La cantidad mínima para mayoreo debe ser "
                "al menos 2 unidades."
            )
        return value