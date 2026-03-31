from django.db import models

class Proveedor(models.Model):
    nombre    = models.CharField(max_length=150)
    nit       = models.CharField(max_length=30, unique=True, blank=True, null=True)
    telefono  = models.CharField(max_length=20, blank=True)
    email     = models.EmailField(blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    ciudad    = models.CharField(max_length=100, blank=True)
    activo    = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = "proveedores"


class Compra(models.Model):
    ESTADO_CHOICES = [
        ("pendiente", "Pendiente"),
        ("recibida",  "Recibida"),
        ("cancelada", "Cancelada"),
    ]
    tienda          = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    proveedor       = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    empleado        = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    numero_orden    = models.CharField(max_length=30, unique=True)
    total           = models.DecimalField(max_digits=12, decimal_places=2)
    estado          = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="pendiente")
    fecha_orden     = models.DateTimeField(auto_now_add=True)
    fecha_recepcion = models.DateTimeField(null=True, blank=True)
    observaciones   = models.TextField(blank=True)

    def __str__(self):
        return f"Orden {self.numero_orden} - {self.proveedor}"

    class Meta:
        db_table = "compras"


class DetalleCompra(models.Model):
    compra          = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.CASCADE)
    cantidad        = models.DecimalField(max_digits=12, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "detalle_compras"
