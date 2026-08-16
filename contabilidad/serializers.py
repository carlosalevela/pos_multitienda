from decimal import Decimal

from rest_framework import serializers

from core.permissions import es_superadmin, get_empresa
from .models import Gasto


class GastoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)
    monto           = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )

    class Meta:
        model  = Gasto
        fields = [
            "id", "tienda", "tienda_nombre",
            "sesion_caja", "empleado", "empleado_nombre",
            "categoria", "descripcion",
            "monto", "metodo_pago", "visibilidad", "tipo_gasto", "created_at",
        ]
        read_only_fields = ["id", "empleado", "created_at"]

    def validate_tienda(self, tienda):
        request = self.context.get("request")
        if request and not es_superadmin(request):
            if tienda.empresa != get_empresa(request):
                raise serializers.ValidationError(
                    "La tienda no pertenece a tu empresa.")
        return tienda

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None