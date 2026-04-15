from rest_framework import serializers
from .models import Proveedor, Compra, DetalleCompra
from productos.models import Categoria


# ── Helper local (reemplaza resolver_categoria importado) ──────
def _resolver_categoria(nombre_cat: str, empresa):
    """Busca o crea categoría DENTRO de la empresa. Nunca mezcla."""
    nombre = ' '.join((nombre_cat or '').split())
    if not nombre:
        return None
    categoria, _ = Categoria.objects.get_or_create(
        nombre__iexact=nombre,
        empresa=empresa,                        # ✅ scoped
        defaults={"nombre": nombre, "empresa": empresa},
    )
    return categoria


# ── Proveedores ────────────────────────────────────────────────

class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = [
            "id", "nombre", "nit", "telefono",
            "email", "direccion", "ciudad",
            "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at", "empresa"]     # ✅


class ProveedorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = ["id", "nombre", "nit"]
        read_only_fields = ["empresa"]                          # ✅


# ── Detalle Compra ─────────────────────────────────────────────

class DetalleCompraSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(
        source="categoria.nombre", read_only=True)
    categoria_nombre_input = serializers.CharField(
        write_only=True, required=False, allow_blank=True, default='')

    class Meta:
        model  = DetalleCompra
        fields = [
            "id", "producto", "producto_nombre",
            "nombre_libre", "categoria", "categoria_nombre",
            "categoria_nombre_input",
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

    def validate_producto(self, producto):
        """Valida que el producto sea de la empresa del usuario."""   # ✅
        if producto is None:
            return producto
        request = self.context.get("request")
        if request and producto.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El producto no pertenece a tu empresa.")
        return producto

    def validate(self, attrs):
        tiene_producto     = attrs.get("producto") is not None
        tiene_nombre_libre = attrs.get("nombre_libre", "").strip()
        if not tiene_producto and not tiene_nombre_libre:
            raise serializers.ValidationError(
                "Debes seleccionar un producto o escribir un nombre.")
        attrs["subtotal"] = attrs["cantidad"] * attrs["precio_unitario"]
        return attrs

    def create(self, validated_data):
        nombre_cat = validated_data.pop("categoria_nombre_input", "") or ""
        if nombre_cat.strip():
            empresa = self.context["request"].user.empresa      # ✅
            validated_data["categoria"] = _resolver_categoria(nombre_cat, empresa)
        return super().create(validated_data)


# ── Compra ─────────────────────────────────────────────────────

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

    def validate_tienda(self, tienda):
        """Valida que la tienda sea de la empresa del usuario."""    # ✅
        request = self.context.get("request")
        if request and tienda.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "La tienda no pertenece a tu empresa.")
        return tienda

    def validate_proveedor(self, proveedor):
        """Valida que el proveedor sea de la empresa del usuario.""" # ✅
        request = self.context.get("request")
        if request and proveedor.empresa != request.user.empresa:
            raise serializers.ValidationError(
                "El proveedor no pertenece a tu empresa.")
        return proveedor

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        empresa       = self.context["request"].user.empresa        # ✅
        total  = sum(d["cantidad"] * d["precio_unitario"] for d in detalles_data)
        compra = Compra.objects.create(total=total, **validated_data)

        for detalle in detalles_data:
            nombre_cat = detalle.pop("categoria_nombre_input", "") or ""
            if nombre_cat.strip() and not detalle.get("categoria"):
                detalle["categoria"] = _resolver_categoria(nombre_cat, empresa)  # ✅
            detalle["subtotal"] = detalle["cantidad"] * detalle["precio_unitario"]
            DetalleCompra.objects.create(compra=compra, **detalle)

        return compra