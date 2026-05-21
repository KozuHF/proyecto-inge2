from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("turnos", "0003_remove_turno_unique_turno_actividad_fecha_hora_and_more"),
        ("actividades", "0003_actividad_precio_turno"),
    ]

    operations = [
        migrations.AddField(
            model_name="reserva",
            name="estado_pago",
            field=models.CharField(
                choices=[("pendiente", "Pago pendiente"), ("pagado", "Pagado")],
                default="pendiente",
                max_length=10,
                verbose_name="Estado de pago",
            ),
        ),
        migrations.AddField(
            model_name="reserva",
            name="precio_abonado",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name="Precio abonado",
            ),
        ),
        migrations.AddField(
            model_name="reserva",
            name="referencia_pago",
            field=models.CharField(
                blank=True,
                max_length=40,
                verbose_name="Referencia de pago",
            ),
        ),
    ]
