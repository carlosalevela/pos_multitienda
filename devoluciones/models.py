from django.db import models
from django.conf import settings


class Devolucion(models.Model):
    METODOS = [
        ("efectivo",      "Efectivo"),
        ("tarjeta",       "Tarjeta"),
        ("nota_credito",  "Nota Crédito"),
    ]
    ESTADOS = [
        ("procesada",  "Procesada"),
        ("cancelada",  "Cancelada"),
    ]

    venta              = models.ForeignKey("ventas.Venta",         on_delete=models.PROTECT, related_name="devoluciones")
    tienda             = models.ForeignKey("tiendas.Tienda",       on_delete=models.PROTECT, related_name="devoluciones")
    empleado           = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    total_devuelto     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metodo_devolucion  = models.CharField(max_length=20, choices=METODOS, default="efectivo")
    estado             = models.CharField(max_length=20, choices=ESTADOS, default="procesada")
    observaciones      = models.TextField(blank=True, null=True)
    created_at         = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"DEV-{self.id} | {self.venta.numero_factura}"


class DetalleDevolucion(models.Model):
    devolucion      = models.ForeignKey(Devolucion, on_delete=models.CASCADE, related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.PROTECT)
    cantidad        = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    motivo          = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.devolucion} - {self.producto.nombre}"