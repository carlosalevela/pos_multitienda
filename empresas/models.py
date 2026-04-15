from django.db import models


class Empresa(models.Model):
    nombre     = models.CharField(max_length=150)
    nit        = models.CharField(max_length=30, unique=True)
    email      = models.EmailField(blank=True)
    telefono   = models.CharField(max_length=20, blank=True)
    direccion  = models.CharField(max_length=200, blank=True)
    ciudad     = models.CharField(max_length=100, blank=True)
    logo       = models.ImageField(upload_to='empresas/logos/', null=True, blank=True)
    activo     = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = "empresas"