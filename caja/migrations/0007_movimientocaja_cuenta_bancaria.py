from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('caja', '0006_alter_movimientocaja_tipo'),
        ('configuracion', '0004_add_cuenta_bancaria'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimientocaja',
            name='cuenta_bancaria',
            field=models.ForeignKey(
                to='configuracion.CuentaBancaria',
                on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True,
                related_name='movimientos',
            ),
        ),
    ]
