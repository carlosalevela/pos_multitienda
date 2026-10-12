from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0001_initial'),
        ('devoluciones', '0005_devolucion_cambio_entregado_devolucion_diferencia_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='devolucion',
            name='cuenta_destino',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='devoluciones',
                to='configuracion.cuentabancaria',
            ),
        ),
    ]
