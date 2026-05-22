import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagos", "0002_pago_tipo_cobro"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pago",
            name="reserva",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="pagos",
                to="turnos.reserva",
                verbose_name="Reserva",
            ),
        ),
    ]
