from rest_framework import serializers
from .models import Proveedor, Compra, DetalleCompra, DistribucionDetalle
from productos.models import Categoria
from core.permissions import es_superadmin, get_empresa


# ── Helper local ───────────────────────────────────────────────
def _resolver_categoria(nombre_cat: str, empresa):
    """Busca o crea categoría DENTRO de la empresa. Nunca mezcla."""
    nombre = ' '.join((nombre_cat or '').split())
    if not nombre:
        return None
    categoria, _ = Categoria.objects.get_or_create(
        nombre__iexact=nombre,
        empresa=empresa,
        defaults={"nombre": nombre, "empresa": empresa},
    )
    return categoria


# ── Proveedores ────────────────────────────────────────────────

class ProveedorSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.CharField(
        source='empresa.nombre', read_only=True)

    class Meta:
        model  = Proveedor
        fields = [
            "id", "nombre", "nit", "telefono",
            "email", "direccion", "ciudad",
            "empresa_id",
            "empresa_nombre",
            "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class ProveedorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model        = Proveedor
        fields       = ["id", "nombre", "nit"]
        read_only_fields = ["empresa"]


# ── Distribución Detalle ───────────────────────────────────────

class DistribucionDetalleSerializer(serializers.ModelSerializer):
    tienda_nombre = serializers.CharField(source="tienda.nombre", read_only=True)

    class Meta:
        model  = DistribucionDetalle
        fields = ["id", "tienda", "tienda_nombre", "cantidad", "cantidad_recibida"]
        read_only_fields = ["id", "cantidad_recibida"]
        extra_kwargs = {
            "tienda":    {"required": True},
            "cantidad":  {"required": True},
        }


# ── Detalle Compra ─────────────────────────────────────────────

class DetalleCompraSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(
        source="categoria.nombre", read_only=True)
    categoria_nombre_input = serializers.CharField(
        write_only=True, required=False,
        allow_blank=True, default='')
    distribuciones = DistribucionDetalleSerializer(many=True, required=False, default=list)

    class Meta:
        model  = DetalleCompra
        fields = [
            "id", "producto", "producto_nombre",
            "nombre_libre", "categoria", "categoria_nombre",
            "categoria_nombre_input",
            "cantidad", "precio_unitario", "precio_venta",
            "codigo_barras_input", "subtotal",
            "distribuciones",
        ]
        read_only_fields = ["id", "subtotal"]
        extra_kwargs = {
            "producto":            {"required": False, "allow_null": True},
            "categoria":           {"required": False, "allow_null": True},
            "precio_venta":        {"required": False, "allow_null": True},
            "codigo_barras_input": {"required": False, "allow_blank": True},
        }

    def get_producto_nombre(self, obj):
        if obj.producto:
            return obj.producto.nombre
        return obj.nombre_libre or "Producto libre"

    def validate_producto(self, producto):
        if producto is None:
            return producto
        request = self.context.get("request")
        if request and not es_superadmin(request):
            if producto.empresa != get_empresa(request):
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
        distribuciones_data = validated_data.pop("distribuciones", [])
        nombre_cat = validated_data.pop("categoria_nombre_input", "") or ""
        if nombre_cat.strip():
            empresa = get_empresa(self.context["request"])
            validated_data["categoria"] = _resolver_categoria(
                nombre_cat, empresa)
        detalle = super().create(validated_data)
        for dist in distribuciones_data:
            DistribucionDetalle.objects.create(detalle=detalle, **dist)
        return detalle


# ── Compra ─────────────────────────────────────────────────────

class CompraSerializer(serializers.ModelSerializer):
    detalles         = DetalleCompraSerializer(many=True)
    proveedor_nombre = serializers.CharField(
        source="proveedor.nombre", read_only=True)
    tienda_nombre    = serializers.SerializerMethodField()
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
            "observaciones", "detalles",
            "a_credito", "fecha_vencimiento", "pagado",
        ]
        read_only_fields = [
            "id", "total", "fecha_orden",
            "empleado", "numero_orden"
        ]
        extra_kwargs = {
            "tienda": {"required": False, "allow_null": True},
        }

    def get_tienda_nombre(self, obj):
        return obj.tienda.nombre if obj.tienda else None

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None

    def validate_tienda(self, tienda):
        if tienda is None:
            return None
        request = self.context.get("request")
        if request and not es_superadmin(request):
            if tienda.empresa != get_empresa(request):
                raise serializers.ValidationError(
                    "La tienda no pertenece a tu empresa.")
        return tienda

    def validate_proveedor(self, proveedor):
        request = self.context.get("request")
        if request and not es_superadmin(request):
            if proveedor.empresa != get_empresa(request):
                raise serializers.ValidationError(
                    "El proveedor no pertenece a tu empresa.")
        return proveedor

    def validate(self, attrs):
        tienda   = attrs.get("tienda")
        detalles = attrs.get("detalles", [])
        if tienda is None and detalles:
            for d in detalles:
                if not d.get("distribuciones"):
                    raise serializers.ValidationError(
                        "En pedidos multi-tienda, todos los productos deben "
                        "especificar la distribución por tienda.")
        return attrs

    def create(self, validated_data):
        detalles_data = validated_data.pop("detalles")
        empresa       = get_empresa(self.context["request"])
        total  = sum(
            d["cantidad"] * d["precio_unitario"]
            for d in detalles_data)
        compra = Compra.objects.create(
            total=total, **validated_data)

        for detalle in detalles_data:
            distribuciones_data = detalle.pop("distribuciones", [])
            nombre_cat = detalle.pop("categoria_nombre_input", "") or ""
            if nombre_cat.strip() and not detalle.get("categoria"):
                detalle["categoria"] = _resolver_categoria(
                    nombre_cat, empresa)
            detalle["subtotal"] = (
                detalle["cantidad"] * detalle["precio_unitario"])
            det_obj = DetalleCompra.objects.create(compra=compra, **detalle)
            for dist in distribuciones_data:
                DistribucionDetalle.objects.create(detalle=det_obj, **dist)

        return compra