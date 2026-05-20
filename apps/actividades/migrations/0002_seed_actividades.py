from django.db import migrations


ACTIVIDADES_INICIALES = [
    {"nombre": "futbol", "cupos": 20},
    {"nombre": "voley",  "cupos": 20},
    {"nombre": "basket", "cupos": 20},
    {"nombre": "paddle", "cupos": 20},
]


def insertar_actividades(apps, schema_editor):
    Actividad = apps.get_model("actividades", "Actividad")
    for datos in ACTIVIDADES_INICIALES:
        Actividad.objects.get_or_create(nombre=datos["nombre"], defaults={"cupos": datos["cupos"]})


def eliminar_actividades(apps, schema_editor):
    Actividad = apps.get_model("actividades", "Actividad")
    Actividad.objects.filter(nombre__in=[a["nombre"] for a in ACTIVIDADES_INICIALES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("actividades", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(insertar_actividades, eliminar_actividades),
    ]