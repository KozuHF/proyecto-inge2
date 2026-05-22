import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("actividades", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SaldoCredito",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cantidad", models.PositiveIntegerField(default=0, verbose_name="Cantidad de créditos")),
                (
                    "actividad",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saldos_credito",
                        to="actividades.actividad",
                        verbose_name="Actividad",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saldos_credito",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Saldo de crédito",
                "verbose_name_plural": "Saldos de crédito",
            },
        ),
        migrations.AddConstraint(
            model_name="saldocredito",
            constraint=models.UniqueConstraint(
                fields=("usuario", "actividad"),
                name="unique_saldo_credito_usuario_actividad",
            ),
        ),
    ]
