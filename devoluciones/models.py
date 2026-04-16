from django.db import models
from django.conf import settings

class Devolucion(models.Model):
    METODOS = [
        ("efectivo",      "Efectivo"),
        ("transferencia", "Transferencia"),
        ("tarjeta",       "Tarjeta"),
        ("nota_credito",  "Nota Crédito"),
    ]
    ESTADOS = [
        ("procesada", "Procesada"),
        ("cancelada", "Cancelada"),
    ]
    TIPOS = [
        ("devolucion", "Devolución"),
        ("cambio",     "Cambio"),
    ]

    venta             = models.ForeignKey("ventas.Venta",           on_delete=models.PROTECT,  related_name="devoluciones")
    tienda            = models.ForeignKey("tiendas.Tienda",         on_delete=models.PROTECT,  related_name="devoluciones")
    empleado          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    total_devuelto    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metodo_devolucion = models.CharField(max_length=20, choices=METODOS, default="efectivo")
    tipo              = models.CharField(max_length=20, choices=TIPOS, default="devolucion")
    estado            = models.CharField(max_length=20, choices=ESTADOS, default="procesada")
    observaciones     = models.TextField(blank=True, default="")
    created_at        = models.DateTimeField(auto_now_add=True)

    # ── Campos de cambio (solo aplican cuando tipo == "cambio") ──
    producto_reemplazo  = models.ForeignKey(
        "productos.Producto",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="cambios_como_reemplazo",
    )
    cantidad_reemplazo  = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["tienda", "-created_at"]),
            models.Index(fields=["venta"]),
            models.Index(fields=["estado"]),
            models.Index(fields=["tipo"]),
        ]

    def __str__(self):
        return f"DEV-{self.id} | {self.venta.numero_factura}"
    METODOS = [
        ("efectivo",      "Efectivo"),
        ("transferencia", "Transferencia"),
        ("tarjeta",       "Tarjeta"),
        ("nota_credito",  "Nota Crédito"),
    ]
    ESTADOS = [
        ("procesada", "Procesada"),
        ("cancelada", "Cancelada"),
    ]

    TIPOS = [                          # ← agrega esto
        ("devolucion", "Devolución"),
        ("cambio",     "Cambio"),
    ]

    venta             = models.ForeignKey("ventas.Venta",           on_delete=models.PROTECT,  related_name="devoluciones")
    tienda            = models.ForeignKey("tiendas.Tienda",         on_delete=models.PROTECT,  related_name="devoluciones")
    empleado          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    total_devuelto    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metodo_devolucion = models.CharField(max_length=20, choices=METODOS, default="efectivo")
    tipo = models.CharField(max_length=20, choices=TIPOS, default="devolucion")
    estado            = models.CharField(max_length=20, choices=ESTADOS, default="procesada")
    observaciones     = models.TextField(blank=True, default="")        # ← quitado null=True
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tienda", "-created_at"]),  # listado principal
            models.Index(fields=["venta"]),                   # validar ya_devuelto
            models.Index(fields=["estado"]),
            models.Index(fields=["tipo"]),                   # filtro por estado
        ]

    def __str__(self):
        return f"DEV-{self.id} | {self.venta.numero_factura}"


class DetalleDevolucion(models.Model):
    devolucion      = models.ForeignKey(Devolucion,           on_delete=models.CASCADE,  related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.PROTECT)
    cantidad        = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    motivo          = models.CharField(max_length=200, blank=True, default="")  # ← quitado null=True

    def save(self, *args, **kwargs):
        self.subtotal = self.cantidad * self.precio_unitario  # ← recalculo seguro
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.devolucion} - {self.producto.nombre}"