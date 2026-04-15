from rest_framework import serializers
from .models import Empresa


class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Empresa
        fields = [
            'id', 'nombre', 'nit', 'email',
            'telefono', 'direccion', 'ciudad',
            'logo', 'activo', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']