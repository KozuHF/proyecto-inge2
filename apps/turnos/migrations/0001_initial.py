from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("actividades", "0002_seed_actividades"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── GrupoReservaMensual ───────────────────────────────────────────
        migrations.CreateModel(
            name="GrupoReservaMensual",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grupos_mensuales",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
                (
                    "actividad",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="grupos_mensuales",
                        to="actividades.actividad",
                        verbose_name="Actividad",
                    ),
                ),
                ("dia_semana",     models.PositiveSmallIntegerField(verbose_name="Día de la semana")),
                ("hora",           models.PositiveSmallIntegerField(verbose_name="Hora")),
                ("anio",           models.PositiveSmallIntegerField(verbose_name="Año")),
                ("mes",            models.PositiveSmallIntegerField(verbose_name="Mes")),
                ("fecha_creacion", models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")),
            ],
            options={
                "verbose_name":        "Grupo de reserva mensual",
                "verbose_name_plural": "Grupos de reserva mensual",
                "ordering":            ["-fecha_creacion"],
            },
        ),

        # ── Turno ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Turno",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "actividad",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="turnos",
                        to="actividades.actividad",
                        verbose_name="Actividad",
                    ),
                ),
                ("fecha", models.DateField(verbose_name="Fecha")),
                (
                    "hora",
                    models.PositiveSmallIntegerField(
                        verbose_name="Hora de inicio",
                        help_text="Hora entera (8–21). El turno dura 1 hora.",
                    ),
                ),
            ],
            options={
                "verbose_name":        "Turno",
                "verbose_name_plural": "Turnos",
                "ordering":            ["fecha", "hora", "actividad"],
            },
        ),
        migrations.AddConstraint(
            model_name="turno",
            constraint=models.UniqueConstraint(
                fields=["actividad", "fecha", "hora"],
                name="unique_turno_actividad_fecha_hora",
            ),
        ),

        # ── Reserva ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Reserva",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "usuario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reservas",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Usuario",
                    ),
                ),
                (
                    "turno",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reservas",
                        to="turnos.turno",
                        verbose_name="Turno",
                    ),
                ),
                (
                    "grupo_mensual",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reservas",
                        to="turnos.gruporeservamensual",
                        verbose_name="Grupo mensual",
                    ),
                ),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("confirmada", "Confirmada"),
                            ("en_espera",  "En lista de espera"),
                            ("cancelada",  "Cancelada"),
                        ],
                        default="confirmada",
                        max_length=12,
                        verbose_name="Estado",
                    ),
                ),
                (
                    "tipo_reserva",
                    models.CharField(
                        choices=[
                            ("individual", "Turno individual"),
                            ("mensual",    "Mensual (mismo día y hora, todo el mes)"),
                        ],
                        default="individual",
                        max_length=10,
                        verbose_name="Tipo de reserva",
                    ),
                ),
                ("fecha_reserva",     models.DateTimeField(auto_now_add=True, verbose_name="Fecha de reserva")),
                ("fecha_cancelacion", models.DateTimeField(blank=True, null=True, verbose_name="Fecha de cancelación")),
            ],
            options={
                "verbose_name":        "Reserva",
                "verbose_name_plural": "Reservas",
                "ordering":            ["-fecha_reserva"],
            },
        ),
        migrations.AddConstraint(
            model_name="reserva",
            constraint=models.UniqueConstraint(
                condition=models.Q(estado__in=["confirmada", "en_espera"]),
                fields=["usuario", "turno"],
                name="unique_reserva_activa_por_usuario_turno",
            ),
        ),
    ]