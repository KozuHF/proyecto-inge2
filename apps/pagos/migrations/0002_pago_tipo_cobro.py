from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagos", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="pago",
            name="tipo_cobro",
            field=models.CharField(
                choices=[
                    ("total", "Pago total"),
                    ("sena", "Seña 50%"),
                    ("saldo", "Saldo restante"),
                ],
                default="total",
                max_length=10,
                verbose_name="Tipo de cobro",
            ),
        ),
    ]
