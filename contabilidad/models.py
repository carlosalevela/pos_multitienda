from django.db import models


class Gasto(models.Model):
    VISIBILIDAD = [
        ('todos',      'Todos'),
        ('solo_admin', 'Solo Admin'),
    ]
    TIPO_GASTO = [
        ('fijo',     'Fijo'),
        ('variable', 'Variable'),
    ]

    tienda       = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    empleado     = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    sesion_caja  = models.ForeignKey("caja.SesionCaja", on_delete=models.SET_NULL, null=True, blank=True)
    categoria    = models.CharField(max_length=80, blank=True)
    descripcion  = models.TextField(blank=True)
    monto        = models.DecimalField(max_digits=12, decimal_places=2)
    metodo_pago  = models.CharField(max_length=20, default="efectivo")
    visibilidad  = models.CharField(
        max_length=20,
        choices=VISIBILIDAD,
        default='todos',
    )
    tipo_gasto   = models.CharField(
        max_length=10,
        choices=TIPO_GASTO,
        default='fijo',
    )
    fecha        = models.DateField(auto_now_add=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gastos"