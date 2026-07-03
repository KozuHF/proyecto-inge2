from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("turnos", "0018_turno_cancelado_por_club"),
    ]

    operations = [
        migrations.AddField(
            model_name="reserva",
            name="incumplimiento_no_abonado",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Marcado cuando el cliente no asistió a una clase suelta señada "
                    "sin completar el pago del saldo."
                ),
                verbose_name="Incumplimiento por seña impaga",
            ),
        ),
    ]
