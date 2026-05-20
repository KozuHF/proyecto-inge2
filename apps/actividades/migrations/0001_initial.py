from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Actividad",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "nombre",
                    models.CharField(
                        choices=[
                            ("futbol", "Fútbol"),
                            ("voley",  "Vóley"),
                            ("basket", "Básquet"),
                            ("paddle", "Pádel"),
                        ],
                        max_length=10,
                        unique=True,
                        verbose_name="Nombre",
                    ),
                ),
                (
                    "cupos",
                    models.PositiveIntegerField(
                        default=20,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Cupos disponibles por turno",
                        help_text="Cantidad máxima de reservas por turno para esta actividad.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Actividad",
                "verbose_name_plural": "Actividades",
                "ordering": ["nombre"],
            },
        ),
    ]