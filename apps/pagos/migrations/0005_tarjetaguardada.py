import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pagos", "0004_pago_creditos_usados"),
    ]

    operations = [
        migrations.CreateModel(
            name="TarjetaGuardada",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pan", models.CharField(max_length=16, verbose_name="Número de tarjeta (normalizado)")),
                ("titular", models.CharField(max_length=100, verbose_name="Titular")),
                ("vencimiento", models.CharField(max_length=5, verbose_name="Vencimiento (MM/AA)")),
                ("ultimos_4", models.CharField(max_length=4, verbose_name="Últimos 4 dígitos")),
                ("fecha_actualizacion", models.DateTimeField(auto_now=True)),
                (
                    "usuario",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tarjeta_guardada",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Tarjeta guardada",
                "verbose_name_plural": "Tarjetas guardadas",
            },
        ),
    ]
