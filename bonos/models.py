import random
import string
from datetime import timedelta

from django.db  import models
from django.utils import timezone


def _generar_codigo():
    chars = string.ascii_uppercase + string.digits
    while True:
        codigo = 'BON-' + ''.join(random.choices(chars, k=6))
        if not Bono.objects.filter(codigo=codigo).exists():
            return codigo


class Bono(models.Model):
    ESTADO_CHOICES = [
        ('activo',    'Activo'),
        ('redimido',  'Redimido'),
        ('vencido',   'Vencido'),
        ('cancelado', 'Cancelado'),
    ]

    codigo            = models.CharField(max_length=20, unique=True)
    empresa           = models.ForeignKey(
        'empresas.Empresa', on_delete=models.CASCADE, related_name='bonos')
    tienda_origen     = models.ForeignKey(
        'tiendas.Tienda', on_delete=models.SET_NULL, null=True,
        related_name='bonos_vendidos')
    valor_original    = models.DecimalField(max_digits=12, decimal_places=2)
    saldo             = models.DecimalField(max_digits=12, decimal_places=2)
    estado            = models.CharField(
        max_length=15, choices=ESTADO_CHOICES, default='activo')
    venta_origen      = models.OneToOneField(
        'ventas.Venta', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bono_generado')
    cliente           = models.ForeignKey(
        'clientes.Cliente', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bonos')
    metodo_pago       = models.CharField(max_length=20, default='efectivo')
    monto_recibido    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fecha_vencimiento = models.DateField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bonos'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = _generar_codigo()
        if not self.fecha_vencimiento:
            self.fecha_vencimiento = (timezone.now() + timedelta(days=365)).date()
        super().save(*args, **kwargs)

    @property
    def esta_vigente(self):
        return (
            self.estado == 'activo'
            and self.saldo > 0
            and self.fecha_vencimiento >= timezone.now().date()
        )

    def __str__(self):
        return f'{self.codigo} | ${self.saldo} | {self.estado}'


class UsoBono(models.Model):
    bono          = models.ForeignKey(
        Bono, on_delete=models.CASCADE, related_name='usos')
    venta         = models.ForeignKey(
        'ventas.Venta', on_delete=models.CASCADE, related_name='usos_bono')
    tienda        = models.ForeignKey(
        'tiendas.Tienda', on_delete=models.SET_NULL, null=True)
    monto_usado   = models.DecimalField(max_digits=12, decimal_places=2)
    saldo_antes   = models.DecimalField(max_digits=12, decimal_places=2)
    saldo_despues = models.DecimalField(max_digits=12, decimal_places=2)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'usos_bono'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.bono.codigo} | -{self.monto_usado} en venta {self.venta_id}'
