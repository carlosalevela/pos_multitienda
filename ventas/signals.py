from django.db.models.signals import post_save
from django.db.models import Sum
from django.dispatch import receiver


@receiver(post_save, sender='ventas.Venta')
def actualizar_acumulado_cliente(sender, instance, **kwargs):
    if not instance.cliente_id:
        return

    from clientes.models import Cliente

    # Recalcula desde cero sumando todas las ventas completadas del cliente.
    # Usar sum en DB evita drift por ediciones manuales o anulaciones.
    total = sender.objects.filter(
        cliente_id=instance.cliente_id,
        estado='completada',
    ).aggregate(s=Sum('total'))['s'] or 0

    Cliente.objects.filter(pk=instance.cliente_id).update(total_acumulado=total)
