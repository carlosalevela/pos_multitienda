from rest_framework import serializers
from .models import Categoria, Producto, Inventario, MovimientoInventario


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Categoria
        fields = ["id", "nombre", "descripcion"]
        read_only_fields = ["id", "empresa"]


class _ProductoInventarioMixin:
    """Métodos compartidos entre ProductoSerializer y ProductoSimpleSerializer."""

    def _get_inventario(self, obj):
        cache     = self.context.setdefault("_inv_cache", {})
        if obj.pk not in cache:
            request   = self.context.get("request")
            tienda_id = request.query_params.get("tienda_id") if request else None
            qs = Inventario.objects.filter(producto=obj)
            if tienda_id:
                qs = qs.filter(tienda_id=tienda_id)
            cache[obj.pk] = qs.first()
        return cache[obj.pk]

    def get_maneja_mayoreo(self, obj):
        return obj.empresa.maneja_mayoreo if obj.empresa else False

    def get_cantidad_mayoreo(self, obj):
        return obj.empresa.cantidad_mayoreo if obj.empresa else None


class ProductoSerializer(_ProductoInventarioMixin, serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    stock_actual     = serializers.SerializerMethodField()
    stock_minimo     = serializers.SerializerMethodField()
    maneja_mayoreo   = serializers.SerializerMethodField()
    cantidad_mayoreo = serializers.SerializerMethodField()

    class Meta:
        model  = Producto
        fields = [
            "id", "nombre", "descripcion", "codigo_barras",
            "imagen",
            "categoria", "categoria_nombre",
            "precio_compra", "precio_venta", "precio_mayoreo",
            "unidad_medida", "aplica_impuesto", "porcentaje_impuesto",
            "activo", "created_at",
            "stock_actual", "stock_minimo",
            "maneja_mayoreo", "cantidad_mayoreo",
        ]
        read_only_fields = ["id", "created_at", "empresa"]

    def get_stock_actual(self, obj):
        inv = self._get_inventario(obj)
        return float(inv.stock_actual) if inv else 0.0

    def get_stock_minimo(self, obj):
        inv = self._get_inventario(obj)
        return float(inv.stock_minimo) if inv else 0.0

    def validate_precio_mayoreo(self, value):
        precio_venta = self.initial_data.get("precio_venta")
        if value is not None and precio_venta is not None:
            if float(value) > float(precio_venta):
                raise serializers.ValidationError(
                    "El precio mayoreo no puede ser mayor al precio de venta normal."
                )
        return value


class ProductoSimpleSerializer(_ProductoInventarioMixin, serializers.ModelSerializer):
    """Para búsquedas rápidas en el POS."""

    stock_actual     = serializers.SerializerMethodField()
    precio_mayoreo   = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    maneja_mayoreo   = serializers.SerializerMethodField()
    cantidad_mayoreo = serializers.SerializerMethodField()
    alerta_stock     = serializers.SerializerMethodField()

    class Meta:
        model  = Producto
        fields = [
            "id", "nombre", "codigo_barras",
            "precio_venta", "precio_mayoreo",
            "maneja_mayoreo", "cantidad_mayoreo",
            "aplica_impuesto", "porcentaje_impuesto",
            "unidad_medida", "stock_actual", "alerta_stock",
        ]
        read_only_fields = ["empresa"]

    def get_stock_actual(self, obj):
        inv = self._get_inventario(obj)
        return float(inv.stock_actual) if inv else 0.0

    def get_alerta_stock(self, obj):
        inv = self._get_inventario(obj)
        if not inv or inv.stock_actual <= 0:
            return "agotado"
        if inv.stock_actual <= inv.stock_minimo:
            return "bajo"
        return "ok"


class InventarioSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.CharField(source="producto.nombre",        read_only=True)
    producto_barcode = serializers.CharField(source="producto.codigo_barras", read_only=True)
    producto_imagen  = serializers.ImageField(source="producto.imagen",       read_only=True)
    precio_venta     = serializers.DecimalField(
        source="producto.precio_venta",  max_digits=12, decimal_places=2, read_only=True)
    precio_compra    = serializers.DecimalField(
        source="producto.precio_compra", max_digits=12, decimal_places=2, read_only=True)
    categoria_nombre = serializers.CharField(source="producto.categoria.nombre", read_only=True)
    tienda_nombre    = serializers.CharField(source="tienda.nombre",          read_only=True)
    alerta_stock     = serializers.SerializerMethodField()

    class Meta:
        model  = Inventario
        fields = [
            "id", "producto", "producto_nombre",
            "producto_barcode", "producto_imagen",
            "categoria_nombre",
            "precio_venta", "precio_compra",
            "tienda", "tienda_nombre",
            "stock_actual", "stock_averias", "stock_minimo", "stock_maximo",
            "alerta_stock", "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def get_alerta_stock(self, obj):
        if obj.stock_actual <= 0:
            return "agotado"
        if obj.stock_actual <= obj.stock_minimo:
            return "bajo"
        return "ok"


class AjusteInventarioSerializer(serializers.Serializer):
    tipo        = serializers.ChoiceField(choices=["entrada", "salida", "ajuste"])
    cantidad    = serializers.DecimalField(max_digits=12, decimal_places=2)
    observacion = serializers.CharField(required=False, allow_blank=True)


class MovimientoInventarioSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    empleado_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = MovimientoInventario
        fields = [
            "id", "producto", "producto_nombre",
            "tienda", "empleado", "empleado_nombre",
            "tipo", "cantidad", "referencia_tipo",
            "observacion", "created_at",
        ]

    def get_empleado_nombre(self, obj):
        if obj.empleado:
            return f"{obj.empleado.nombre} {obj.empleado.apellido}"
        return None


class ImportarProductoItemSerializer(serializers.Serializer):
    """Valida cada fila del Excel antes de crear el producto."""

    nombre           = serializers.CharField(max_length=150)
    descripcion      = serializers.CharField(required=False, allow_blank=True, default='')
    codigo_barras    = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None)
    categoria_nombre = serializers.CharField(required=False, allow_blank=True, default='')
    precio_venta     = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_compra    = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_mayoreo   = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None)
    stock_actual     = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo     = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_maximo     = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None)
