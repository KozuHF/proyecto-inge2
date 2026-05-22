from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagos", "0003_pago_reserva_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="pago",
            name="creditos_usados",
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name="Créditos utilizados",
            ),
        ),
    ]
