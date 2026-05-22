from decimal import Decimal

from django.db import migrations, models
import django.core.validators


PRECIOS = {
    "futbol": Decimal("9000.00"),
    "voley": Decimal("8000.00"),
    "basket": Decimal("8500.00"),
    "paddle": Decimal("12000.00"),
}


def asignar_precios(apps, schema_editor):
    Actividad = apps.get_model("actividades", "Actividad")
    for nombre, precio in PRECIOS.items():
        Actividad.objects.filter(nombre=nombre).update(precio_turno=precio)


class Migration(migrations.Migration):

    dependencies = [
        ("actividades", "0002_seed_actividades"),
    ]

    operations = [
        migrations.AddField(
            model_name="actividad",
            name="precio_turno",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5000.00"),
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="Precio por turno",
            ),
        ),
        migrations.RunPython(asignar_precios, migrations.RunPython.noop),
    ]
