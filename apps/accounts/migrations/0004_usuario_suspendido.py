from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_crear_admin_defecto"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="suspendido",
            field=models.BooleanField(
                default=False,
                help_text="Suspensión por incumplimiento de plazos de abono mensual u otras sanciones.",
                verbose_name="Suspendido",
            ),
        ),
    ]
