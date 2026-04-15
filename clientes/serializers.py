from rest_framework import serializers
from .models import Cliente, Separado, DetalleSeparado, AbonoSeparado


class ClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Cliente
        fields = [
            "id", "nombre", "apellido", "cedula_nit",
            "telefono", "email", "direccion",
            "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at", "empresa"]   # ✅


class ClienteSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Cliente
        fields = ["id", "nombre", "apellido", "cedula_nit", "telefono"]
        read_only_fields = ["empresa"]                         # ✅


class DetalleSeparadoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)

    class Meta:
        model  = DetalleSeparado
        fields = ["id", "producto", "producto_nombre",
                  "cantidad", "precio_unitario", "subtotal"]
        read_only_fields = ["id", "subtotal"]

    def validate_producto(self, producto):
        """Valida que el producto pertenezca a la empresa del usuario."""  # ✅
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El producto no pertenece a tu empresa.")
        return producto

    def validate(self, attrs):
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs


class AbonoSeparadoSerializer(serializers.ModelSerializer):
    empleado_nombre = serializers.SerializerMethodField()
    cliente_nombre  = serializers.SerializerMethodField()

    class Meta:
        model  = AbonoSeparado
        fields = ["id", "separado", "empleado", "empleado_nombre",
                  "cliente_nombre",
                  "monto", "metodo_pago", "created_at"]
        read_only_fields = ["id", "empleado", "created_at"]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def get_cliente_nombre(self, obj):
        if obj.separado and obj.separado.cliente:
            c = obj.separado.cliente
            return f"{c.nombre} {c.apellido}"
        return "—"


class SeparadoSerializer(serializers.ModelSerializer):
    detalles        = DetalleSeparadoSerializer(many=True)
    abonos          = AbonoSeparadoSerializer(many=True, read_only=True)
    cliente_nombre  = serializers.SerializerMethodField()
    tienda_nombre   = serializers.CharField(source="tienda.nombre", read_only=True)
    empleado_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = Separado
        fields = [
            "id", "tienda", "tienda_nombre",
            "cliente", "cliente_nombre",
            "empleado", "empleado_nombre",
            "total", "abono_acumulado", "saldo_pendiente",
            "fecha_limite", "estado",
            "created_at", "detalles", "abonos"
        ]
        read_only_fields = [
            "id", "total", "abono_acumulado",
            "saldo_pendiente", "empleado", "created_at"
        ]

    def get_cliente_nombre(self, obj):
        return f"{obj.cliente.nombre} {obj.cliente.apellido}"

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def validate_tienda(self, tienda):
        """Valida que la tienda pertenezca a la empresa del usuario."""  # ✅
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

    def validate_cliente(self, cliente):
        """Valida que el cliente pertenezca a la empresa del usuario."""  # ✅
        request = self.context.get("request")
        if request and cliente.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El cliente no pertenece a tu empresa.")
        return cliente

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        total = sum(d["cantidad"] * d["precio_unitario"] for d in detalles_data)
        separado = Separado.objects.create(
            total           = total,
            saldo_pendiente = total,
            abono_acumulado = 0,
            **validated_data
        )
        for detalle in detalles_data:
            detalle["subtotal"] = detalle["cantidad"] * detalle["precio_unitario"]
            DetalleSeparado.objects.create(separado=separado, **detalle)
        return separado