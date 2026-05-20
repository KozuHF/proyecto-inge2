from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _


class Actividad(models.Model):
    """
    Actividades deportivas disponibles en el establecimiento.

    Las actividades son fijas (Fútbol, Vóley, Básquet, Pádel) y se crean
    mediante una migración de datos. NO se pueden agregar nuevas actividades
    desde la interfaz; los cupos sí son modificables.

    Preparado para agregar precio por turno en el futuro:
        precio_turno = models.DecimalField(...)  # descomentar cuando corresponda
    """

    class Nombre(models.TextChoices):
        FUTBOL  = "futbol",  _("Fútbol")
        VOLEY   = "voley",   _("Vóley")
        BASKET  = "basket",  _("Básquet")
        PADDLE  = "paddle",  _("Pádel")

    CUPOS_DEFAULT = 20

    nombre = models.CharField(
        max_length=10,
        choices=Nombre.choices,
        unique=True,
        verbose_name=_("Nombre"),
    )
    cupos = models.PositiveIntegerField(
        default=CUPOS_DEFAULT,
        validators=[MinValueValidator(1)],
        verbose_name=_("Cupos disponibles por turno"),
        help_text=_("Cantidad máxima de reservas por turno para esta actividad."),
    )

    # ── Gancho para precios futuros ───────────────────────────────────────────
    # precio_turno = models.DecimalField(
    #     max_digits=8, decimal_places=2,
    #     null=True, blank=True,
    #     verbose_name=_("Precio por turno"),
    # )

    class Meta:
        verbose_name = _("Actividad")
        verbose_name_plural = _("Actividades")
        ordering = ["nombre"]

    def __str__(self):
        return self.get_nombre_display()