from django.db import models


class Categoria(models.Model):
    empresa     = models.ForeignKey(                    # ✅ nuevo
        "empresas.Empresa", on_delete=models.CASCADE,
        null=True, blank=True, related_name="categorias"
    )
    nombre      = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = "categorias"


class Producto(models.Model):
    empresa           = models.ForeignKey(              # ✅ nuevo
        "empresas.Empresa", on_delete=models.CASCADE,
        null=True, blank=True, related_name="productos"
    )
    categoria         = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name="productos")
    nombre            = models.CharField(max_length=150)
    descripcion       = models.TextField(blank=True)
    codigo_barras     = models.CharField(max_length=50, unique=True, blank=True, null=True)
    precio_compra     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    precio_venta      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unidad_medida     = models.CharField(max_length=30, default="unidad")
    aplica_impuesto   = models.BooleanField(default=False)
    porcentaje_impuesto = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    activo            = models.BooleanField(default=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = "productos"


class Inventario(models.Model):
    producto     = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="inventarios")
    tienda       = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE, related_name="inventarios")
    stock_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_maximo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at   = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.producto} - {self.tienda}: {self.stock_actual}"

    class Meta:
        db_table        = "inventario"
        unique_together = ("producto", "tienda")


class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ("entrada",       "Entrada"),
        ("salida",        "Salida"),
        ("ajuste",        "Ajuste"),
        ("transferencia", "Transferencia"),
    ]
    producto        = models.ForeignKey(Producto, on_delete=models.CASCADE)
    tienda          = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    empleado        = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    tipo            = models.CharField(max_length=20, choices=TIPO_CHOICES)
    cantidad        = models.DecimalField(max_digits=12, decimal_places=2)
    referencia_tipo = models.CharField(max_length=30, blank=True)
    referencia_id   = models.IntegerField(null=True, blank=True)
    observacion     = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "movimientos_inventario"


def generar_codigo_barras_interno():
    codigos = (
        Producto.objects
        .filter(codigo_barras__regex=r'^1\d{7,}$')
        .values_list('codigo_barras', flat=True)
    )
    if not codigos.exists():
        return '10000001'
    max_num = max(int(c) for c in codigos if c and c.isdigit())
    return str(max_num + 1)