from django.db import models
from tiendas.models import Tienda


class TierConfig(models.Model):
    empresa       = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='tiers')
    nombre        = models.CharField(max_length=50)
    umbral_min    = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # null = sin límite superior (tier más alto)
    umbral_max    = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    descuento_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    color_hex     = models.CharField(max_length=7, default='#76777D')
    activo        = models.BooleanField(default=True)
    orden         = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'tier_configs'
        ordering = ['orden', 'umbral_min']
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'nombre'],
                name='tier_nombre_empresa_uniq'
            )
        ]

    def __str__(self):
        return f"{self.empresa.nombre} – {self.nombre}"


class Cliente(models.Model):
    empresa  = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE)
    tienda   = models.ForeignKey(
        Tienda,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='clientes'
    )
    nombre          = models.CharField(max_length=100)
    apellido        = models.CharField(max_length=100, blank=True)
    cedula_nit      = models.CharField(max_length=30, blank=True, null=True)
    telefono        = models.CharField(max_length=20, blank=True)
    email           = models.EmailField(blank=True)
    direccion       = models.CharField(max_length=200, blank=True)
    activo          = models.BooleanField(default=True)
    total_acumulado = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at      = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def tier_actual(self):
        return TierConfig.objects.filter(
            empresa=self.empresa,
            activo=True,
            umbral_min__lte=self.total_acumulado,
        ).filter(
            models.Q(umbral_max__isnull=True) | models.Q(umbral_max__gt=self.total_acumulado)
        ).order_by('-umbral_min').first()

    class Meta:
        db_table = "clientes"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cedula_nit"],
                condition=models.Q(cedula_nit__isnull=False),
                name="unique_cedula_por_empresa"
            )
        ]


class Separado(models.Model):
    ESTADO_CHOICES = [
        ("activo",    "Activo"),
        ("pagado",    "Pagado"),
        ("cancelado", "Cancelado"),
    ]
    tienda          = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    cliente         = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    empleado        = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    total           = models.DecimalField(max_digits=12, decimal_places=2)
    abono_acumulado = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    saldo_pendiente = models.DecimalField(max_digits=12, decimal_places=2)
    fecha_limite    = models.DateField(null=True, blank=True)
    estado          = models.CharField(max_length=15, choices=ESTADO_CHOICES, default="activo")
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "separados"


class DetalleSeparado(models.Model):
    separado        = models.ForeignKey(Separado, on_delete=models.CASCADE, related_name="detalles")
    producto        = models.ForeignKey("productos.Producto", on_delete=models.CASCADE)
    cantidad        = models.DecimalField(max_digits=12, decimal_places=2)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "detalle_separados"


class AbonoSeparado(models.Model):
    separado    = models.ForeignKey(Separado, on_delete=models.CASCADE, related_name="abonos")
    empleado    = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    monto       = models.DecimalField(max_digits=12, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, default="efectivo")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "abonos_separados"
