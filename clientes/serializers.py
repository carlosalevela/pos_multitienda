from rest_framework import serializers

from core.permissions import get_empresa
from .models import Cliente, Separado, DetalleSeparado, AbonoSeparado, TierConfig


# ─── TierConfig ─────────────────────────────────────────────────────────────
class TierConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TierConfig
        fields = [
            'id', 'empresa', 'nombre', 'umbral_min', 'umbral_max',
            'descuento_pct', 'color_hex', 'activo', 'orden',
        ]
        read_only_fields = ['id', 'empresa']

    def validate_nombre(self, value):
        request = self.context.get('request')
        empresa = get_empresa(request)
        qs = TierConfig.objects.filter(empresa=empresa, nombre__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un tier con ese nombre.')
        return value


# ─── Helper compartido ────────────────────────────────────────────────────────
def _tier_info(obj):
    tier = obj.tier_actual
    if tier is None:
        return None
    return {
        'id':            tier.id,
        'nombre':        tier.nombre,
        'descuento_pct': float(tier.descuento_pct),
        'color_hex':     tier.color_hex,
    }


# ─── Cliente ────────────────────────────────────────────────────────────────
class ClienteSerializer(serializers.ModelSerializer):
    tier_info = serializers.SerializerMethodField()

    class Meta:
        model  = Cliente
        fields = [
            'id', 'empresa', 'tienda', 'nombre', 'apellido', 'cedula_nit',
            'telefono', 'email', 'direccion',
            'activo', 'total_acumulado', 'tier_info', 'created_at',
        ]
        read_only_fields = ['id', 'empresa', 'total_acumulado', 'created_at']

    def get_tier_info(self, obj):
        return _tier_info(obj)

    def validate_cedula_nit(self, value):
        if not value:
            return value
        request = self.context.get('request')
        empresa = get_empresa(request)
        qs = Cliente.objects.filter(empresa=empresa, cedula_nit=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                'Ya existe un cliente con esta cédula/NIT en tu empresa.')
        return value


class ClienteSimpleSerializer(serializers.ModelSerializer):
    tier_info = serializers.SerializerMethodField()

    class Meta:
        model  = Cliente
        fields = ['id', 'nombre', 'apellido', 'cedula_nit', 'telefono', 'tier_info']

    def get_tier_info(self, obj):
        return _tier_info(obj)


# ─── Detalle Separado ────────────────────────────────────────────────────────
class DetalleSeparadoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)

    class Meta:
        model  = DetalleSeparado
        fields = ['id', 'producto', 'producto_nombre',
                  'cantidad', 'precio_unitario', 'subtotal']
        read_only_fields = ['id', 'subtotal']

    def validate_producto(self, producto):
        request = self.context.get('request')
        empresa = get_empresa(request)
        if empresa and producto.empresa != empresa:
            raise serializers.ValidationError(
                'El producto no pertenece a tu empresa.')
        return producto

    def validate(self, attrs):
        attrs['subtotal'] = attrs['cantidad'] * attrs['precio_unitario']
        return attrs


# ─── Abono Separado ──────────────────────────────────────────────────────────
class AbonoSeparadoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    cliente_nombre  = serializers.SerializerMethodField()

    class Meta:
        model  = AbonoSeparado
        fields = ['id', 'separado', 'empleado', 'empleado_nombre',
                  'cliente_nombre', 'monto', 'metodo_pago', 'created_at']
        read_only_fields = ['id', 'empleado', 'created_at']

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f'{obj.empleado.nombre} {obj.empleado.apellido}'
        return None

    def get_cliente_nombre(self, obj):
        if obj.separado and obj.separado.cliente:
            c = obj.separado.cliente
            return f'{c.nombre} {c.apellido}'
        return '—'


# ─── Separado ────────────────────────────────────────────────────────────────
class SeparadoSerializer(serializers.ModelSerializer):
    detalles        = DetalleSeparadoSerializer(many=True)
    abonos          = AbonoSeparadoSerializer(many=True, read_only=True)
    cliente_nombre  = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source='tienda.nombre', read_only=True)
    empleado_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = Separado
        fields = [
            'id', 'tienda', 'tienda_nombre',
            'cliente', 'cliente_nombre',
            'empleado', 'empleado_nombre',
            'total', 'abono_acumulado', 'saldo_pendiente',
            'fecha_limite', 'estado',
            'created_at', 'detalles', 'abonos',
        ]
        read_only_fields = [
            'id', 'total', 'abono_acumulado',
            'saldo_pendiente', 'empleado', 'created_at',
        ]

    def get_cliente_nombre(self, obj):
        return f'{obj.cliente.nombre} {obj.cliente.apellido}'

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f'{obj.empleado.nombre} {obj.empleado.apellido}'
        return None

    def validate_tienda(self, tienda):
        request = self.context.get('request')
        empresa = get_empresa(request)
        if empresa and tienda.empresa != empresa:
            raise serializers.ValidationError(
                'La tienda no pertenece a tu empresa.')
        return tienda

    def validate_cliente(self, cliente):
        request = self.context.get('request')
        empresa = get_empresa(request)
        if empresa and cliente.empresa != empresa:
            raise serializers.ValidationError(
                'El cliente no pertenece a tu empresa.')
        return cliente

    def validate(self, attrs):
        tienda  = attrs.get('tienda')
        cliente = attrs.get('cliente')
        if tienda and cliente and tienda.empresa != cliente.empresa:
            raise serializers.ValidationError(
                'La tienda y el cliente deben pertenecer a la misma empresa.')
        return attrs

    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles')
        total = sum(d['cantidad'] * d['precio_unitario'] for d in detalles_data)
        separado = Separado.objects.create(
            total           = total,
            saldo_pendiente = total,
            abono_acumulado = 0,
            **validated_data
        )
        for detalle in detalles_data:
            detalle['subtotal'] = detalle['cantidad'] * detalle['precio_unitario']
            DetalleSeparado.objects.create(separado=separado, **detalle)
        return separado
