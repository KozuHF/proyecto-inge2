from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .constants import DIAS_VALIDEZ_CREDITO


class Credito(models.Model):
    """
    Crédito individual con vencimiento a 30 días desde su otorgamiento.
    Se consumen en orden FIFO (el que vence antes primero).
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creditos",
        verbose_name=_("Usuario"),
    )
    actividad = models.ForeignKey(
        "actividades.Actividad",
        on_delete=models.CASCADE,
        related_name="creditos",
        verbose_name=_("Actividad"),
    )
    fecha_otorgamiento = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de otorgamiento"),
    )
    fecha_vencimiento = models.DateTimeField(
        verbose_name=_("Fecha de vencimiento"),
    )
    consumido_en = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Fecha de uso"),
    )
    reserva_origen = models.ForeignKey(
        "turnos.Reserva",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creditos_generados",
        verbose_name=_("Reserva que originó el crédito"),
    )

    class Meta:
        verbose_name = _("Crédito")
        verbose_name_plural = _("Créditos")
        ordering = ["fecha_vencimiento", "fecha_otorgamiento"]
        indexes = [
            models.Index(
                fields=["usuario", "actividad", "consumido_en", "fecha_vencimiento"],
                name="credito_disp_idx",
            ),
        ]

    def __str__(self):
        estado = _("usado") if self.consumido_en else _("disponible")
        return f"{self.usuario} – {self.actividad} ({estado})"

    @classmethod
    def calcular_vencimiento(cls, desde=None):
        desde = desde or timezone.now()
        return desde + timedelta(days=DIAS_VALIDEZ_CREDITO)

    @property
    def esta_disponible(self) -> bool:
        return (
            self.consumido_en is None
            and self.fecha_vencimiento > timezone.now()
        )
