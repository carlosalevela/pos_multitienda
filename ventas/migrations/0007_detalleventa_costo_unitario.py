from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ventas', '0006_consecutivofactura'),
    ]

    operations = [
        migrations.AddField(
            model_name='detalleventa',
            name='costo_unitario',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
    ]
