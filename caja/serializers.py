from rest_framework import serializers
from .models import SesionCaja


class SesionCajaSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)
    total_ventas    = serializers.SerializerMethodField()
    total_gastos    = serializers.SerializerMethodField()

    class Meta:
        model  = SesionCaja
        fields = [
            "id", "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "fecha_apertura", "fecha_cierre",
            "monto_inicial", "monto_final_sistema",
            "monto_final_real", "diferencia",
            "total_ventas", "total_gastos",
            "observaciones", "estado"
        ]
        read_only_fields = [
            "id", "empleado", "fecha_apertura", "fecha_cierre",
            "monto_final_sistema", "diferencia", "estado"
        ]

    def validate_tienda(self, tienda):
        """Valida que la tienda sea de la empresa del usuario."""  # ✅
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def get_total_ventas(self, obj):
        from ventas.models import Venta
        from django.db.models import Sum
        total = Venta.objects.filter(
            sesion_caja=obj, estado="completada"
        ).aggregate(t=Sum("total"))["t"]
        return float(total or 0)

    def get_total_gastos(self, obj):
        from contabilidad.models import Gasto
        from django.db.models import Sum
        total = Gasto.objects.filter(
            sesion_caja=obj
        ).aggregate(t=Sum("monto"))["t"]
        return float(total or 0)


class AbrirCajaSerializer(serializers.Serializer):
    monto_inicial = serializers.DecimalField(max_digits=12, decimal_places=2)


class CerrarCajaSerializer(serializers.Serializer):
    monto_final_real = serializers.DecimalField(max_digits=12, decimal_places=2)
    observaciones    = serializers.CharField(required=False, allow_blank=True)