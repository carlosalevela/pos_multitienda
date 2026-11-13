from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('devoluciones', '0006_devolucion_cuenta_destino'),
        ('productos', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DetalleReemplazo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cantidad', models.DecimalField(decimal_places=2, max_digits=10)),
                ('precio_unitario', models.DecimalField(decimal_places=2, max_digits=12)),
                ('subtotal', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('devolucion', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reemplazos',
                    to='devoluciones.devolucion',
                )),
                ('producto', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to='productos.producto',
                )),
            ],
        ),
    ]
