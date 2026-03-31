from django.db import models

class Gasto(models.Model):
    tienda       = models.ForeignKey("tiendas.Tienda", on_delete=models.CASCADE)
    empleado     = models.ForeignKey("usuarios.Empleado", on_delete=models.SET_NULL, null=True)
    sesion_caja  = models.ForeignKey("caja.SesionCaja", on_delete=models.SET_NULL, null=True, blank=True)
    categoria    = models.CharField(max_length=80, blank=True)  # arriendo, nomina, servicios...
    descripcion  = models.TextField(blank=True)
    monto        = models.DecimalField(max_digits=12, decimal_places=2)
    metodo_pago  = models.CharField(max_length=20, default="efectivo")
    fecha        = models.DateField(auto_now_add=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gastos"
