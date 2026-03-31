from django.db import models
from django.conf import settings


class Venta(models.Model):
    METODOS_PAGO = [
        ("efectivo",   "Efectivo"),
        ("tarjeta",    "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("mixto",      "Mixto"),
    ]
    ESTADOS = [
        ("completada", "Completada"),
        ("anulada",    "Anulada"),
    ]

    numero_factura  = models.CharField(max_length=20, unique=True)
    tienda          = models.ForeignKey("tiendas.Tienda",    on_delete=models.PROTECT, related_name="ventas")
    sesion_caja     = models.ForeignKey("caja.SesionCaja",   on_delete=models.PROTECT, related_name="ventas")
    cliente         = models.ForeignKey("clientes.Cliente",  on_delete=models.SET_NULL, null=True, blank=True)
    empleado        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 👈
    impuesto_total  = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # 👈
    total           = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    metodo_pago     = models.CharField(max_length=20, choices=METODOS_PAGO, default="efectivo")
    monto_recibido  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vuelto          = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    estado          = models.CharField(max_length=20, choices=ESTADOS, default="completada")
    observaciones   = models.TextField(blank=True, null=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.numero_factura


class DetalleVenta(models.Model):
    venta           = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.PROTECT)
    cantidad        = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    descuento       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.venta.numero_factura} - {self.producto.nombre}"