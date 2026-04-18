from django.db import models
from django.conf import settings


class Venta(models.Model):
    METODOS_PAGO = [
        ("efectivo",      "Efectivo"),
        ("tarjeta",       "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("mixto",         "Mixto"),
    ]
    ESTADOS = [
        ("completada", "Completada"),
        ("anulada",    "Anulada"),
    ]

    numero_factura  = models.CharField(max_length=20, unique=True)
    tienda          = models.ForeignKey("tiendas.Tienda",         on_delete=models.PROTECT,  related_name="ventas")
    sesion_caja     = models.ForeignKey("caja.SesionCaja",        on_delete=models.PROTECT,  related_name="ventas")
    cliente         = models.ForeignKey("clientes.Cliente",       on_delete=models.SET_NULL, null=True, blank=True)
    empleado        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    impuesto_total  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Pago principal (compatibilidad hacia atrás) ──────────────────────────
    # Se mantiene para ventas normales (un solo método).
    # En ventas mixtas (cambio POS) este campo se marca como "mixto"
    # y el detalle real queda en PagoVenta.
    metodo_pago    = models.CharField(max_length=20, choices=METODOS_PAGO, default="efectivo")
    monto_recibido = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vuelto         = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    estado        = models.CharField(max_length=20, choices=ESTADOS, default="completada")
    observaciones = models.TextField(blank=True, null=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tienda", "-created_at"]),
            models.Index(fields=["sesion_caja"]),
            models.Index(fields=["estado"]),
        ]

    def __str__(self):
        return self.numero_factura

    # ── Helpers ──────────────────────────────────────────────────────────────

    @property
    def total_pagado(self):
        """Suma real de todos los pagos registrados en PagoVenta."""
        return self.pagos.aggregate(
            total=models.Sum("monto")
        )["total"] or 0

    @property
    def saldo_pendiente(self):
        """Diferencia entre lo que se debe y lo que se pagó."""
        from decimal import Decimal
        return Decimal(str(self.total)) - Decimal(str(self.total_pagado))


class DetalleVenta(models.Model):
    venta           = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.PROTECT)
    cantidad        = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    descuento       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.venta.numero_factura} - {self.producto.nombre}"


# ── NUEVO ─────────────────────────────────────────────────────────────────────

class PagoVenta(models.Model):
    """
    Registro de cada pago aplicado a una venta.

    Una venta normal tiene 1 PagoVenta.
    Un cambio POS puede tener N pagos (efectivo + transferencia, etc.).
    También se usa para registrar el valor reconocido por devolución de productos.
    """

    METODOS = [
        ("efectivo",      "Efectivo"),
        ("tarjeta",       "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("nota_credito",  "Nota Crédito"),
        ("devolucion",    "Reconocimiento por devolución"),  # ← saldo a favor
    ]

    venta  = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="pagos")
    metodo = models.CharField(max_length=20, choices=METODOS)
    monto  = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        indexes = [
            models.Index(fields=["venta"]),
        ]

    def __str__(self):
        return f"{self.venta.numero_factura} | {self.metodo} | {self.monto}"
