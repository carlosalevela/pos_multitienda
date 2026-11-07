from rest_framework import serializers
from .models import Bono, UsoBono


class UsoBonoSerializer(serializers.ModelSerializer):
    tienda_nombre = serializers.CharField(source='tienda.nombre', read_only=True)

    class Meta:
        model  = UsoBono
        fields = [
            'id', 'monto_usado', 'saldo_antes', 'saldo_despues',
            'tienda_nombre', 'venta', 'created_at',
        ]


class BonoSerializer(serializers.ModelSerializer):
    usos          = UsoBonoSerializer(many=True, read_only=True)
    esta_vigente  = serializers.BooleanField(read_only=True)
    tienda_origen_nombre = serializers.CharField(
        source='tienda_origen.nombre', read_only=True)
    cliente_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = Bono
        fields = [
            'id', 'codigo', 'valor_original', 'saldo', 'estado',
            'esta_vigente', 'fecha_vencimiento', 'created_at',
            'tienda_origen_nombre', 'cliente_nombre',
            'venta_origen', 'usos',
        ]

    def get_cliente_nombre(self, obj):
        if obj.cliente:
            return f'{obj.cliente.nombre} {obj.cliente.apellido or ""}'.strip()
        return None


class BonoListSerializer(serializers.ModelSerializer):
    esta_vigente         = serializers.BooleanField(read_only=True)
    tienda_origen_nombre = serializers.CharField(
        source='tienda_origen.nombre', read_only=True)

    class Meta:
        model  = Bono
        fields = [
            'id', 'codigo', 'valor_original', 'saldo', 'estado',
            'esta_vigente', 'fecha_vencimiento', 'created_at',
            'tienda_origen_nombre',
        ]


class ValidarBonoSerializer(serializers.Serializer):
    codigo = serializers.CharField()


class RedimirBonoSerializer(serializers.Serializer):
    codigo     = serializers.CharField()
    monto      = serializers.DecimalField(max_digits=12, decimal_places=2)
    venta_id   = serializers.IntegerField()
    tienda_id  = serializers.IntegerField()
