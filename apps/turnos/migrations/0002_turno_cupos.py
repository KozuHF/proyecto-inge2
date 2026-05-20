from django.db import migrations, models


def inicializar_cupos_desde_actividad(apps, schema_editor):
    """
    Para los turnos ya existentes, copia los cupos de su actividad.
    En instalaciones nuevas no hay turnos, así que no hace nada.
    """
    Turno = apps.get_model("turnos", "Turno")
    for turno in Turno.objects.select_related("actividad").all():
        turno.cupos = turno.actividad.cupos
        turno.save(update_fields=["cupos"])


class Migration(migrations.Migration):

    dependencies = [
        ("turnos", "0001_initial"),
    ]

    operations = [
        # Agregar el campo con un default temporal para que la migración no falle
        # en bases de datos con filas existentes (default=20 = valor de Actividad).
        migrations.AddField(
            model_name="turno",
            name="cupos",
            field=models.PositiveIntegerField(
                default=20,
                verbose_name="Cupos",
                help_text="Cupos disponibles para este turno. Se inicializa con el valor de la actividad pero puede modificarse individualmente.",
            ),
            preserve_default=False,
        ),
        # Sincronizar filas existentes con el valor real de su actividad.
        migrations.RunPython(
            inicializar_cupos_desde_actividad,
            migrations.RunPython.noop,
        ),
    ]