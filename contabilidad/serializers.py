from rest_framework import serializers
from .models import Gasto


class GastoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)

    class Meta:
        model  = Gasto
        fields = [
            "id", "tienda", "tienda_nombre",
            "sesion_caja", "empleado", "empleado_nombre",
            "categoria", "descripcion",
            "monto", "metodo_pago", "created_at"
        ]
        read_only_fields = ["id", "empleado", "created_at"]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None