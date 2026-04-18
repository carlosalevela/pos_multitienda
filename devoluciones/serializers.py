from decimal import Decimal
from rest_framework import serializers
from .models import Devolucion, DetalleDevolucion


class DetalleDevolucionSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)

    class Meta:
        model = DetalleDevolucion
        fields = [
            "id", "producto", "producto_nombre",
            "cantidad", "precio_unitario", "subtotal", "motivo",
        ]
        read_only_fields = ["id", "subtotal"]

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0.")
        return value

    def validate_precio_unitario(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio unitario debe ser mayor a 0.")
        return value

    def validate_producto(self, producto):
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError("El producto no pertenece a tu empresa.")
        return producto

    def validate(self, attrs):
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs


class DevolucionSerializer(serializers.ModelSerializer):
    detalles = DetalleDevolucionSerializer(many=True)
    empleado_nombre = serializers.SerializerMethodField()
    tienda_nombre = serializers.CharField(source="tienda.nombre", read_only=True)
    venta_numero = serializers.CharField(source="venta.numero_factura", read_only=True)

    producto_reemplazo_nombre = serializers.CharField(source="producto_reemplazo.nombre", read_only=True)
    precio_reemplazo = serializers.SerializerMethodField()
    subtotal_reemplazo = serializers.SerializerMethodField()

    class Meta:
        model = Devolucion
        fields = [
            "id", "venta", "venta_numero",
            "tienda", "tienda_nombre",
            "empleado", "empleado_nombre",
            "total_devuelto", "metodo_devolucion",
            "tipo",
            "producto_reemplazo",
            "producto_reemplazo_nombre",
            "cantidad_reemplazo",
            "precio_reemplazo",
            "subtotal_reemplazo",
            "total_reemplazo",
            "diferencia",
            "tipo_diferencia",
            "metodo_pago_diferencia",
            "monto_recibido",
            "cambio_entregado",
            "estado", "observaciones",
            "created_at", "detalles",
        ]
        read_only_fields = [
            "id", "empleado", "tienda",
            "total_devuelto", "estado", "created_at",
            "precio_reemplazo",
            "subtotal_reemplazo",
        ]

    def get_empleado_nombre(self, obj):
        if not obj.empleado:
            return None
        partes = filter(None, [obj.empleado.nombre, obj.empleado.apellido])
        return " ".join(partes) or None

    def get_precio_reemplazo(self, obj):
        if obj.producto_reemplazo:
            return obj.producto_reemplazo.precio_venta
        return None

    def get_subtotal_reemplazo(self, obj):
        if obj.producto_reemplazo and obj.cantidad_reemplazo:
            return obj.producto_reemplazo.precio_venta * obj.cantidad_reemplazo
        return None

    def validate_venta(self, venta):
        request = self.context.get("request")
        if request and venta.tienda.empresa != request.user.empresa:
            raise serializers.ValidationError("La venta no pertenece a tu empresa.")
        if venta.estado == "anulada":
            raise serializers.ValidationError("No se puede devolver una venta anulada.")
        return venta

    def validate_producto_reemplazo(self, producto):
        request = self.context.get("request")
        if producto and request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError("El producto de reemplazo no pertenece a tu empresa.")
        return producto

    def validate_detalles(self, value):
        if not value:
            raise serializers.ValidationError("Debes incluir al menos un producto a devolver.")
        ids = [d["producto"].id for d in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("No puedes repetir el mismo producto en la devolución.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)

        tipo = attrs.get("tipo", "devolucion")
        producto_reemplazo = attrs.get("producto_reemplazo")
        cantidad_reemplazo = attrs.get("cantidad_reemplazo")
        metodo_pago_diferencia = attrs.get("metodo_pago_diferencia")
        monto_recibido = attrs.get("monto_recibido")

        if tipo == "cambio":
            if not producto_reemplazo:
                raise serializers.ValidationError({"producto_reemplazo": "Debes indicar el producto de reemplazo."})
            if not cantidad_reemplazo or cantidad_reemplazo <= 0:
                raise serializers.ValidationError({"cantidad_reemplazo": "La cantidad de reemplazo debe ser mayor a 0."})
            if producto_reemplazo.activo is False:
                raise serializers.ValidationError({"producto_reemplazo": "El producto de reemplazo está inactivo."})

            total_devuelto = sum(d["cantidad"] * d["precio_unitario"] for d in attrs.get("detalles", []))
            total_reemplazo = producto_reemplazo.precio_venta * cantidad_reemplazo
            diferencia_real = total_reemplazo - total_devuelto

            if diferencia_real > 0:
                if not metodo_pago_diferencia:
                    raise serializers.ValidationError({"metodo_pago_diferencia": "Debes indicar cómo se pagará la diferencia."})
                if monto_recibido is None or monto_recibido <= 0:
                    raise serializers.ValidationError({"monto_recibido": "Debes indicar el monto recibido."})
                if monto_recibido < diferencia_real:
                    raise serializers.ValidationError({"monto_recibido": "El monto recibido no cubre la diferencia."})

        return attrs

    def get_fields(self):
        fields = super().get_fields()
        fields["detalles"].child.context.update(self.context)
        return fields

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        producto_reemplazo = validated_data.pop("producto_reemplazo", None)
        cantidad_reemplazo = validated_data.pop("cantidad_reemplazo", None)
        total_reemplazo = validated_data.pop("total_reemplazo", None)
        diferencia = validated_data.pop("diferencia", Decimal("0.00"))
        tipo_diferencia = validated_data.pop("tipo_diferencia", "exacto")
        metodo_pago_diferencia = validated_data.pop("metodo_pago_diferencia", "")
        monto_recibido = validated_data.pop("monto_recibido", None)
        cambio_entregado = validated_data.pop("cambio_entregado", None)

        total_devuelto = sum(d["subtotal"] for d in detalles_data)

        if total_reemplazo is None and producto_reemplazo and cantidad_reemplazo:
            total_reemplazo = producto_reemplazo.precio_venta * cantidad_reemplazo

        if cambio_entregado is None:
            cambio_entregado = Decimal("0.00")

        devolucion = Devolucion.objects.create(
            total_devuelto=total_devuelto,
            total_reemplazo=total_reemplazo,
            diferencia=diferencia,
            tipo_diferencia=tipo_diferencia,
            metodo_pago_diferencia=metodo_pago_diferencia,
            monto_recibido=monto_recibido,
            cambio_entregado=cambio_entregado,
            producto_reemplazo=producto_reemplazo,
            cantidad_reemplazo=cantidad_reemplazo,
            estado="procesada",
            **validated_data,
        )

        DetalleDevolucion.objects.bulk_create([
            DetalleDevolucion(devolucion=devolucion, **d)
            for d in detalles_data
        ])

        return devolucion
