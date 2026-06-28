from django.db import models


METODOS_PAGO_DEFAULT = ["efectivo", "tarjeta", "transferencia", "mixto"]


class ConfigTienda(models.Model):
    POLITICA_CHOICES = [
        ("retener",  "Retener abono"),
        ("devolver", "Devolver abono"),
    ]

    tienda = models.OneToOneField(
        "tiendas.Tienda", on_delete=models.CASCADE,
        related_name="config"
    )

    # ── Moneda ────────────────────────────────────────────────
    moneda_simbolo = models.CharField(max_length=5,  default="$")
    moneda_codigo  = models.CharField(max_length=5,  default="USD")

    # ── Impuestos ─────────────────────────────────────────────
    iva_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Tasa de IVA en % (ej: 12.00). 0 = sin IVA."
    )

    # ── Métodos de pago habilitados ───────────────────────────
    metodos_pago = models.JSONField(
        default=list,
        help_text='Ej: ["efectivo","tarjeta","transferencia","mixto"]'
    )

    # ── Mayoreo ───────────────────────────────────────────────
    habilitar_mayoreo = models.BooleanField(
        default=False,
        help_text="Activa precios mayoreo en el POS de esta tienda."
    )
    umbral_mayoreo = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Unidades mínimas para precio mayoreo en esta tienda. "
                  "Si es null, usa el umbral global de la empresa."
    )

    # ── Separados ─────────────────────────────────────────────
    abono_minimo_pct     = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        help_text="% mínimo del total que el cliente debe abonar al apartar."
    )
    dias_max_liquidar    = models.PositiveIntegerField(
        default=30,
        help_text="Días máximos para liquidar un separado antes de vencer."
    )
    politica_cancelacion = models.CharField(
        max_length=10, choices=POLITICA_CHOICES, default="retener",
        help_text="Qué hacer con el abono si el cliente cancela el separado."
    )
    dias_alerta_separados = models.PositiveIntegerField(
        default=3,
        help_text="Días de anticipación para alertar sobre separados próximos a vencer."
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_tienda"

    def __str__(self):
        return f"Config — {self.tienda}"

    def save(self, *args, **kwargs):
        if not self.metodos_pago:
            self.metodos_pago = METODOS_PAGO_DEFAULT
        super().save(*args, **kwargs)


class ConfigImpresion(models.Model):
    PAPEL_CHOICES = [
        ("80mm", "Térmica 80mm"),
        ("58mm", "Térmica 58mm"),
        ("pdf",  "PDF / A4"),
    ]

    tienda = models.OneToOneField(
        "tiendas.Tienda", on_delete=models.CASCADE,
        related_name="config_impresion"
    )

    tipo_papel         = models.CharField(
        max_length=5, choices=PAPEL_CHOICES, default="80mm"
    )
    copias             = models.PositiveIntegerField(default=1)
    mostrar_logo       = models.BooleanField(default=True)
    mostrar_nit        = models.BooleanField(default=True)
    mensaje_pie        = models.CharField(
        max_length=200, blank=True,
        help_text='Ej: "¡Gracias por su compra! Vuelva pronto."'
    )
    nombre_dispositivo = models.CharField(
        max_length=150, blank=True,
        help_text="Nombre exacto de la impresora en el sistema operativo."
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_impresion"

    def __str__(self):
        return f"Impresión {self.tipo_papel} — {self.tienda}"
