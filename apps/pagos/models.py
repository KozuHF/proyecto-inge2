import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Pago(models.Model):
    """
    Registro de cada intento de pago (aprobado o rechazado).
    La reserva asociada actualiza su estado_pago solo cuando el pago es aprobado.
    """

    class Estado(models.TextChoices):
        APROBADO = "aprobado", _("Aprobado")
        RECHAZADO = "rechazado", _("Rechazado")

    class TipoCobro(models.TextChoices):
        TOTAL = "total", _("Pago total")
        SENA = "sena", _("Seña 50%")
        SALDO = "saldo", _("Saldo restante")

    reserva = models.ForeignKey(
        "turnos.Reserva",
        on_delete=models.CASCADE,
        related_name="pagos",
        verbose_name=_("Reserva"),
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pagos",
        verbose_name=_("Usuario"),
    )
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Monto"),
    )
    tipo_cobro = models.CharField(
        max_length=10,
        choices=TipoCobro.choices,
        default=TipoCobro.TOTAL,
        verbose_name=_("Tipo de cobro"),
    )
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        verbose_name=_("Estado del intento"),
    )
    referencia = models.CharField(
        max_length=40,
        blank=True,
        verbose_name=_("Referencia"),
        help_text=_("Generada solo en pagos aprobados."),
    )
    ultimos_4 = models.CharField(
        max_length=4,
        verbose_name=_("Últimos 4 dígitos"),
    )
    motivo_rechazo = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Motivo de rechazo"),
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha"))

    class Meta:
        verbose_name = _("Pago")
        verbose_name_plural = _("Pagos")
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.referencia or 'rechazado'} – {self.reserva} ({self.get_estado_display()})"

    @classmethod
    def generar_referencia(cls) -> str:
        return f"PAY-{uuid.uuid4().hex[:12].upper()}"
