from django.db import models, transaction
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

    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.PROTECT,
        related_name="ventas",
    )

    numero_factura  = models.CharField(max_length=20)
    tienda          = models.ForeignKey(
        "tiendas.Tienda",
        on_delete=models.PROTECT,
        related_name="ventas",
    )
    sesion_caja     = models.ForeignKey(
        "caja.SesionCaja",
        on_delete=models.PROTECT,
        related_name="ventas",
    )
    cliente         = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    empleado        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )

    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    impuesto_total  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Pago principal (compatibilidad hacia atrás) ──────────────────────────
    metodo_pago     = models.CharField(
        max_length=20,
        choices=METODOS_PAGO,
        default="efectivo",
    )
    monto_recibido  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vuelto          = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    estado          = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default="completada",
    )
    observaciones   = models.TextField(blank=True, null=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["empresa", "tienda", "-created_at"]),
            models.Index(fields=["sesion_caja"]),
            models.Index(fields=["estado"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero_factura"],
                name="venta_empresa_numero_factura_uniq",
            ),
        ]

    def __str__(self):
        return self.numero_factura

    # ── Helper para número de factura ────────────────────────────────────────
    @classmethod
    def generar_numero_factura(cls, empresa):
        from .models import ConsecutivoFactura  # evita referencia circular si el modelo está abajo
        nuevo_num = ConsecutivoFactura.siguiente_numero(empresa)
        return f"FAC-{nuevo_num:06d}"
    
    # ── Helpers de pagos ─────────────────────────────────────────────────────
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
    venta           = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="detalles",
    )
    producto        = models.ForeignKey("productos.Producto", on_delete=models.PROTECT)
    cantidad        = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    descuento       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.venta.numero_factura} - {self.producto.nombre}"


class PagoVenta(models.Model):
    """
    Registro de cada pago aplicado a una venta.
    """

    METODOS = [
        ("efectivo",      "Efectivo"),
        ("tarjeta",       "Tarjeta"),
        ("transferencia", "Transferencia"),
        ("nota_credito",  "Nota Crédito"),
        ("devolucion",    "Reconocimiento por devolución"),
    ]

    venta  = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    metodo = models.CharField(max_length=20, choices=METODOS)
    monto  = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        indexes = [
            models.Index(fields=["venta"]),
        ]

    def __str__(self):
        return f"{self.venta.numero_factura} | {self.metodo} | {self.monto}"
    
class ConsecutivoFactura(models.Model):
    empresa = models.OneToOneField(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="consecutivo_factura",
    )
    ultimo_numero = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.empresa.nombre} → {self.ultimo_numero}"

    @classmethod
    def siguiente_numero(cls, empresa):
        """
        Devuelve el siguiente número entero para la empresa,
        sin saltos por borrados y seguro en concurrencia.
        """
        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(
                empresa=empresa,
                defaults={"ultimo_numero": 0},
            )
            obj.ultimo_numero += 1
            obj.save(update_fields=["ultimo_numero"])
            return obj.ultimo_numero