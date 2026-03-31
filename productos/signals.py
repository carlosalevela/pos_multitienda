#from django.db.models.signals import post_save
#from django.dispatch import receiver
#from .models import Producto, Inventario
#from tiendas.models import Tienda


#@receiver(post_save, sender=Producto)
#def crear_inventario_en_tiendas(sender, instance, created, **kwargs):
    #"""
    #Al crear un producto nuevo, crea automáticamente
    #un registro de inventario (stock 0) en cada tienda activa.
    #"""
    #if created:
        #tiendas = Tienda.objects.filter(activo=True)
        #inventarios = [
            #Inventario(
                #producto     = instance,
                #tienda       = tienda,
                #stock_actual = 0,
                #stock_minimo = 0,
                #stock_maximo = 0,
            #)
            #for tienda in tiendas
        #]
        #Inventario.objects.bulk_create(inventarios, ignore_conflicts=True)