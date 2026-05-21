import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("turnos", "0004_reserva_estado_pago"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Pago",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("monto", models.DecimalField(decimal_places=2, max_digits=10, verbose_name="Monto")),
                (
                    "estado",
                    models.CharField(
                        choices=[("aprobado", "Aprobado"), ("rechazado", "Rechazado")],
                        max_length=10,
                        verbose_name="Estado del intento",
                    ),
                ),
                (
                    "referencia",
                    models.CharField(
                        blank=True,
                        help_text="Generada solo en pagos aprobados.",
                        max_length=40,
                        verbose_name="Referencia",
                    ),
                ),
                ("ultimos_4", models.CharField(max_length=4, verbose_name="Últimos 4 dígitos")),
                ("motivo_rechazo", models.CharField(blank=True, max_length=200, verbose_name="Motivo de rechazo")),
                ("fecha", models.DateTimeField(auto_now_add=True, verbose_name="Fecha")),
                (
                    "reserva",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pagos",
                        to="turnos.reserva",
                        verbose_name="Reserva",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pagos",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Pago",
                "verbose_name_plural": "Pagos",
                "ordering": ["-fecha"],
            },
        ),
    ]
