from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SaldoCredito(models.Model):
    """Saldo de créditos por usuario y deporte (independientes entre sí)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saldos_credito",
        verbose_name=_("Usuario"),
    )
    actividad = models.ForeignKey(
        "actividades.Actividad",
        on_delete=models.CASCADE,
        related_name="saldos_credito",
        verbose_name=_("Actividad"),
    )
    cantidad = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Cantidad de créditos"),
    )

    class Meta:
        verbose_name = _("Saldo de crédito")
        verbose_name_plural = _("Saldos de crédito")
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "actividad"],
                name="unique_saldo_credito_usuario_actividad",
            ),
        ]

    def __str__(self):
        return f"{self.usuario} – {self.actividad}: {self.cantidad}"
