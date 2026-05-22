from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("turnos", "0004_reserva_estado_pago"),
    ]

    operations = [
        migrations.AddField(
            model_name="gruporeservamensual",
            name="regla_cobro",
            field=models.CharField(
                default="primera_quincena",
                max_length=20,
                verbose_name="Regla de cobro",
            ),
        ),
        migrations.AddField(
            model_name="gruporeservamensual",
            name="descuento_porcentaje",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                max_digits=5,
                verbose_name="Descuento (%)",
            ),
        ),
    ]
