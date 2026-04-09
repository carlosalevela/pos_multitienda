from rest_framework import serializers
from .models import Proveedor, Compra, DetalleCompra
from productos.utils import resolver_categoria  # ← agrega este import


class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = [
            "id", "nombre", "nit", "telefono",
            "email", "direccion", "ciudad",
            "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class ProveedorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = ["id", "nombre", "nit"]


class DetalleCompraSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.SerializerMethodField()

    # ← Lee el nombre de la categoría existente (read)
    categoria_nombre = serializers.CharField(
        source="categoria.nombre", read_only=True
    )
    # ← Acepta el nombre para crear/buscar categoría (write)
    categoria_nombre_input = serializers.CharField(
        write_only=True, required=False, allow_blank=True, default=''
    )

    class Meta:
        model  = DetalleCompra
        fields = [
            "id", "producto", "producto_nombre",
            "nombre_libre", "categoria", "categoria_nombre",
            "categoria_nombre_input",  # ← campo de entrada
            "cantidad", "precio_unitario", "subtotal"
        ]
        read_only_fields = ["id", "subtotal"]
        extra_kwargs = {
            "producto":  {"required": False, "allow_null": True},
            "categoria": {"required": False, "allow_null": True},
        }

    def get_producto_nombre(self, obj):
        if obj.producto:
            return obj.producto.nombre
        return obj.nombre_libre or "Producto libre"

    def validate(self, attrs):
        tiene_producto     = attrs.get("producto") is not None
        tiene_nombre_libre = attrs.get("nombre_libre", "").strip()
        if not tiene_producto and not tiene_nombre_libre:
            raise serializers.ValidationError(
                "Debes seleccionar un producto o escribir un nombre."
            )
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs

    def create(self, validated_data):
        nombre_cat = validated_data.pop("categoria_nombre_input", "") or ""
        if nombre_cat.strip():
            validated_data["categoria"] = resolver_categoria(nombre_cat)
        return super().create(validated_data)


class CompraSerializer(serializers.ModelSerializer):
    detalles         = DetalleCompraSerializer(many=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    tienda_nombre    = serializers.CharField(source="tienda.nombre",    read_only=True)
    empleado_nombre  = serializers.SerializerMethodField()

    class Meta:
        model  = Compra
        fields = [
            "id", "numero_orden",
            "tienda", "tienda_nombre",
            "proveedor", "proveedor_nombre",
            "empleado", "empleado_nombre",
            "total", "estado",
            "fecha_orden", "fecha_recepcion",
            "observaciones", "detalles"
        ]
        read_only_fields = ["id", "total", "fecha_orden", "empleado", "numero_orden"]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        total  = sum(d["cantidad"] * d["precio_unitario"] for d in detalles_data)
        compra = Compra.objects.create(total=total, **validated_data)

        for detalle in detalles_data:
            # ✅ Extraer categoria_nombre_input ANTES de crear el objeto
            nombre_cat = detalle.pop("categoria_nombre_input", "") or ""
            if nombre_cat.strip() and not detalle.get("categoria"):
                detalle["categoria"] = resolver_categoria(nombre_cat)

            detalle["subtotal"] = detalle["cantidad"] * detalle["precio_unitario"]
            DetalleCompra.objects.create(compra=compra, **detalle)

        return compra