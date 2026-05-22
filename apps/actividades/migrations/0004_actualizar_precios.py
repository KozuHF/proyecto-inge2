from decimal import Decimal

from django.db import migrations


PRECIOS = {
    "futbol": Decimal("9000.00"),
    "voley": Decimal("8000.00"),
    "basket": Decimal("8500.00"),
    "paddle": Decimal("12000.00"),
}


def actualizar_precios(apps, schema_editor):
    Actividad = apps.get_model("actividades", "Actividad")
    for nombre, precio in PRECIOS.items():
        Actividad.objects.filter(nombre=nombre).update(precio_turno=precio)


class Migration(migrations.Migration):

    dependencies = [
        ("actividades", "0003_actividad_precio_turno"),
    ]

    operations = [
        migrations.RunPython(actualizar_precios, migrations.RunPython.noop),
    ]
