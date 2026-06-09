import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.turnos.models import Reserva


class Asistencia(models.Model):
    """
    Registro de asistencia de un cliente a una clase (reserva) mediante QR.

    Se genera de forma diferida cuando el cliente ve el QR de una reserva
    pagada por completo. El `codigo` es lo que viaja dentro del QR; el empleado
    lo escanea y se marca `presente`.
    """

    reserva = models.OneToOneField(
        Reserva,
        on_delete=models.CASCADE,
        related_name="asistencia",
        verbose_name=_("Reserva"),
    )
    codigo = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name=_("Código QR"),
    )
    presente = models.BooleanField(
        default=False,
        verbose_name=_("Presente"),
    )
    fecha_registro = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de registro"),
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asistencias_registradas",
        verbose_name=_("Registrado por"),
    )

    class Meta:
        verbose_name = _("Asistencia")
        verbose_name_plural = _("Asistencias")
        ordering = ["-fecha_registro"]

    def __str__(self):
        estado = "presente" if self.presente else "pendiente"
        return f"Asistencia {self.reserva} [{estado}]"
