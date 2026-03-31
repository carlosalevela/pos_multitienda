from django.db import models

class SesionCaja(models.Model):
    ESTADO_CHOICES = [("abierta", "Abierta"), ("cerrada", "Cerrada")]

    tienda               = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    empleado             = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    fecha_apertura       = models.DateTimeField(auto_now_add=True)
    fecha_cierre         = models.DateTimeField(null=True, blank=True)
    monto_inicial        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monto_final_sistema  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monto_final_real     = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    diferencia           = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    observaciones        = models.TextField(blank=True)
    estado               = models.CharField(max_length=15, choices=ESTADO_CHOICES, default="abierta")

    def __str__(self):
        return f"Caja {self.tienda} - {self.fecha_apertura.date()} [{self.estado}]"

    class Meta:
        db_table = "sesiones_caja"
