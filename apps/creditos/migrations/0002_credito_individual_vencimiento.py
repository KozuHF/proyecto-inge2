from datetime import timedelta

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def migrar_saldos_a_creditos(apps, schema_editor):
    SaldoCredito = apps.get_model("creditos", "SaldoCredito")
    Credito = apps.get_model("creditos", "Credito")
    ahora = timezone.now()
    vence = ahora + timedelta(days=30)

    for saldo in SaldoCredito.objects.select_related("usuario", "actividad"):
        for _ in range(saldo.cantidad):
            Credito.objects.create(
                usuario_id=saldo.usuario_id,
                actividad_id=saldo.actividad_id,
                fecha_otorgamiento=ahora,
                fecha_vencimiento=vence,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("turnos", "0005_grupo_regla_cobro"),
        ("creditos", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Credito",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fecha_otorgamiento", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de otorgamiento")),
                ("fecha_vencimiento", models.DateTimeField(verbose_name="Fecha de vencimiento")),
                ("consumido_en", models.DateTimeField(blank=True, null=True, verbose_name="Fecha de uso")),
                (
                    "actividad",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="creditos",
                        to="actividades.actividad",
                        verbose_name="Actividad",
                    ),
                ),
                (
                    "reserva_origen",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="creditos_generados",
                        to="turnos.reserva",
                        verbose_name="Reserva que originó el crédito",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="creditos",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
            ],
            options={
                "verbose_name": "Crédito",
                "verbose_name_plural": "Créditos",
                "ordering": ["fecha_vencimiento", "fecha_otorgamiento"],
            },
        ),
        migrations.AddIndex(
            model_name="credito",
            index=models.Index(
                fields=["usuario", "actividad", "consumido_en", "fecha_vencimiento"],
                name="credito_disp_idx",
            ),
        ),
        migrations.RunPython(migrar_saldos_a_creditos, migrations.RunPython.noop),
        migrations.DeleteModel(
            name="SaldoCredito",
        ),
    ]
