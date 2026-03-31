from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Tienda
from productos.models import Producto, Inventario


@receiver(post_save, sender=Tienda)
def crear_inventario_para_nueva_tienda(sender, instance, created, **kwargs):
    """
    Al crear una tienda nueva, crea inventario (stock 0)
    para todos los productos activos existentes.
    """
    if created:
        productos = Producto.objects.filter(activo=True)
        inventarios = [
            Inventario(
                producto     = producto,
                tienda       = instance,
                stock_actual = 0,
                stock_minimo = 0,
                stock_maximo = 0,
            )
            for producto in productos
        ]
        Inventario.objects.bulk_create(inventarios, ignore_conflicts=True)