from django.db import models


TIPO_CHOICES = [
    ('venta',      'Venta'),
    ('separado',   'Separado'),
    ('abono',      'Abono'),
    ('cierre',     'Cierre de caja'),
    ('devolucion', 'Devolución'),
    ('reporte',    'Reporte'),
    ('inventario', 'Inventario'),
    ('compra',     'Orden de compra'),
    ('recepcion',  'Recepción'),
]


class Documento(models.Model):
    tienda   = models.ForeignKey('tiendas.Tienda',    on_delete=models.CASCADE,  related_name='documentos')
    empleado = models.ForeignKey('usuarios.Empleado', on_delete=models.SET_NULL, related_name='documentos', null=True, blank=True)
    tipo     = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nombre   = models.CharField(max_length=255)
    contenido = models.BinaryField()
    size_kb  = models.IntegerField(default=0)
    fecha    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.tipo} — {self.nombre} ({self.tienda})"
