from rest_framework import serializers
from .models import Categoria, Producto, Inventario, MovimientoInventario


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Categoria
        fields = ["id", "nombre", "descripcion"]
        read_only_fields = ["id", "empresa"]        # ✅ empresa nunca viene del frontend


class ProductoSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(
        source="categoria.nombre", read_only=True)
    stock_actual = serializers.SerializerMethodField()
    stock_minimo = serializers.SerializerMethodField()

    class Meta:
        model  = Producto
        fields = [
            "id", "nombre", "descripcion", "codigo_barras",
            "categoria", "categoria_nombre",
            "precio_compra", "precio_venta",
            "unidad_medida", "aplica_impuesto",
            "porcentaje_impuesto", "activo", "created_at",
            "stock_actual", "stock_minimo",
        ]
        read_only_fields = ["id", "created_at", "empresa"]  # ✅

    def _get_inventario(self, obj):
        """
        Resuelve el inventario UNA sola vez por objeto y lo cachea
        en el contexto del serializer para evitar doble query.
        """
        cache = self.context.setdefault("_inv_cache", {})
        if obj.pk not in cache:
            request   = self.context.get("request")
            tienda_id = request.query_params.get("tienda_id") if request else None
            qs = Inventario.objects.filter(producto=obj)
            if tienda_id:
                qs = qs.filter(tienda_id=tienda_id)
            cache[obj.pk] = qs.first()
        return cache[obj.pk]

    def get_stock_actual(self, obj):
        inv = self._get_inventario(obj)
        return float(inv.stock_actual) if inv else 0.0

    def get_stock_minimo(self, obj):
        inv = self._get_inventario(obj)
        return float(inv.stock_minimo) if inv else 0.0


class ProductoSimpleSerializer(serializers.ModelSerializer):
    """Para búsquedas rápidas en el POS"""
    stock_actual = serializers.SerializerMethodField()

    class Meta:
        model  = Producto
        fields = [
            "id", "nombre", "codigo_barras", "precio_venta",
            "aplica_impuesto", "porcentaje_impuesto",
            "unidad_medida", "stock_actual",
        ]
        read_only_fields = ["empresa"]              # ✅

    def get_stock_actual(self, obj):
        cache = self.context.setdefault("_inv_cache", {})
        if obj.pk not in cache:
            request   = self.context.get("request")
            tienda_id = request.query_params.get("tienda_id") if request else None
            qs = Inventario.objects.filter(producto=obj)
            if tienda_id:
                qs = qs.filter(tienda_id=tienda_id)
            cache[obj.pk] = qs.first()
        return float(cache[obj.pk].stock_actual) if cache[obj.pk] else 0.0


class InventarioSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.CharField(source="producto.nombre", read_only=True)
    producto_barcode = serializers.CharField(source="producto.codigo_barras", read_only=True)
    tienda_nombre    = serializers.CharField(source="tienda.nombre", read_only=True)
    alerta_stock     = serializers.SerializerMethodField()

    class Meta:
        model  = Inventario
        fields = [
            "id", "producto", "producto_nombre", "producto_barcode",
            "tienda", "tienda_nombre",
            "stock_actual", "stock_minimo", "stock_maximo",
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