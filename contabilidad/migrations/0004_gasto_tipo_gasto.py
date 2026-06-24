from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0003_gasto_visibilidad'),
    ]

    operations = [
        migrations.AddField(
            model_name='gasto',
            name='tipo_gasto',
            field=models.CharField(
                choices=[('fijo', 'Fijo'), ('variable', 'Variable')],
                default='fijo',
                max_length=10,
            ),
        ),
    ]
