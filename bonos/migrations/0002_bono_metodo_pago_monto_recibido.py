from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bonos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='bono',
            name='metodo_pago',
            field=models.CharField(default='efectivo', max_length=20),
        ),
        migrations.AddField(
            model_name='bono',
            name='monto_recibido',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
    ]
