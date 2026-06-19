from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('productos', '0005_add_imagen_producto_dano_movimiento'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventario',
            name='stock_averias',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
