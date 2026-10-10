from rest_framework import serializers
from .models import Documento


class DocumentoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.SerializerMethodField()
    empresa_nombre  = serializers.SerializerMethodField()

    class Meta:
        model  = Documento
        fields = ['id', 'tipo', 'nombre', 'fecha', 'size_kb',
                  'empleado_nombre', 'tienda_nombre', 'empresa_nombre']

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}".strip()
        return ''

    def get_tienda_nombre(self, obj):
        return obj.tienda.nombre

    def get_empresa_nombre(self, obj):
        return obj.tienda.empresa.nombre if obj.tienda.empresa else ''


class DocumentoUploadSerializer(serializers.Serializer):
    tienda_id = serializers.IntegerField()
    tipo      = serializers.CharField(max_length=20)
    nombre    = serializers.CharField(max_length=255)
    archivo   = serializers.FileField()
