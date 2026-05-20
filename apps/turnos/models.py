from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad


# ── Constantes de negocio ─────────────────────────────────────────────────────

HORA_APERTURA  = 8   # 08:00
HORA_CIERRE    = 22  # 22:00 → último turno inicia a las 21:00
DIAS_HABILES   = [0, 1, 2, 3, 4, 5]  # Lunes=0 … Sábado=5 (domingo=6 cerrado)
HORAS_VALIDAS  = list(range(HORA_APERTURA, HORA_CIERRE))  # [8, 9, …, 21]

# Ventana para reserva mensual: días 1 al 10 del mes en curso
DIA_INICIO_VENTANA_MENSUAL = 1
DIA_FIN_VENTANA_MENSUAL    = 10


def _validar_dia_habil(fecha: "datetime.date"):
    if fecha.weekday() not in DIAS_HABILES:
        raise ValidationError(_("El establecimiento no abre los domingos."))


def _validar_hora(hora: int):
    if hora not in HORAS_VALIDAS:
        raise ValidationError(
            _("El horario debe estar entre las %(apertura)s:00 y las %(cierre)s:00.")
            % {"apertura": HORA_APERTURA, "cierre": HORA_CIERRE - 1}
        )


def _validar_no_pasado(fecha):
    hoy = timezone.now().date()
    if fecha < hoy:
        raise ValidationError(_("No se puede reservar un turno en una fecha pasada."))


# ── Turno ─────────────────────────────────────────────────────────────────────

class Turno(models.Model):
    """
    Representa un bloque horario de 1 hora para una actividad en una fecha concreta.

    Un Turno es la unidad central del sistema: múltiples Reservas apuntan al mismo
    Turno. El modelo NO guarda precio; el campo está preparado para ser agregado.

    Restricciones de negocio:
    - Fecha debe ser un día hábil (lun–sáb).
    - Hora debe estar en [HORA_APERTURA, HORA_CIERRE).
    - La combinación (actividad, fecha, hora) es única.
    """

    actividad = models.ForeignKey(
        Actividad,
        on_delete=models.PROTECT,
        related_name="turnos",
        verbose_name=_("Actividad"),
    )
    fecha = models.DateField(verbose_name=_("Fecha"))
    hora  = models.PositiveSmallIntegerField(
        verbose_name=_("Hora de inicio"),
        help_text=_("Hora entera (8–21). El turno dura 1 hora."),
    )
    cupos = models.PositiveIntegerField(
        verbose_name=_("Cupos"),
        help_text=_("Cupos disponibles para este turno. Se inicializa con el valor de la actividad pero puede modificarse individualmente."),
    )

    # ── Gancho para precios futuros ───────────────────────────────────────────
    # precio_override = models.DecimalField(
    #     max_digits=8, decimal_places=2,
    #     null=True, blank=True,
    #     verbose_name=_("Precio especial (override)"),
    #     help_text=_("Si se completa, reemplaza el precio de la actividad."),
    # )

    class Meta:
        verbose_name        = _("Turno")
        verbose_name_plural = _("Turnos")
        unique_together     = [("actividad", "fecha", "hora")]
        ordering            = ["fecha", "hora", "actividad"]

    def __str__(self):
        return f"{self.actividad} – {self.fecha} {self.hora:02d}:00"

    # ── Validaciones de modelo ────────────────────────────────────────────────

    def clean(self):
        _validar_dia_habil(self.fecha)
        _validar_hora(self.hora)

    # ── Propiedades calculadas ────────────────────────────────────────────────

    @property
    def cupos_totales(self) -> int:
        return self.cupos

    @property
    def reservas_confirmadas(self):
        return self.reservas.filter(estado=Reserva.Estado.CONFIRMADA)

    @property
    def cupos_ocupados(self) -> int:
        return self.reservas_confirmadas.count()

    @property
    def cupos_libres(self) -> int:
        return max(0, self.cupos_totales - self.cupos_ocupados)

    @property
    def esta_lleno(self) -> bool:
        return self.cupos_libres == 0

    @property
    def lista_espera(self):
        return self.reservas.filter(estado=Reserva.Estado.EN_ESPERA).order_by("fecha_reserva")

    # ── Precio efectivo (para uso futuro) ─────────────────────────────────────
    # @property
    # def precio_efectivo(self):
    #     return self.precio_override or self.actividad.precio_turno


# ── Reserva ───────────────────────────────────────────────────────────────────

class Reserva(models.Model):
    """
    Reserva individual de un usuario para un Turno.

    Estados:
    - CONFIRMADA : el usuario tiene un cupo asegurado.
    - EN_ESPERA  : el turno estaba lleno; el usuario queda en lista de espera.
    - CANCELADA  : el usuario canceló (o fue cancelada por el sistema).

    Flujo de lista de espera:
    Al cancelar una reserva CONFIRMADA, el sistema promueve automáticamente
    al primero de la lista de espera (ver método `Reserva.cancelar()`).

    Preparado para pagos:
    - `precio_abonado` y `referencia_pago` están comentados pero listos.
    """

    class Estado(models.TextChoices):
        CONFIRMADA = "confirmada", _("Confirmada")
        EN_ESPERA  = "en_espera",  _("En lista de espera")
        CANCELADA  = "cancelada",  _("Cancelada")

    class TipoReserva(models.TextChoices):
        INDIVIDUAL = "individual", _("Turno individual")
        MENSUAL    = "mensual",    _("Mensual (mismo día y hora, todo el mes)")

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reservas",
        verbose_name=_("Usuario"),
    )
    turno = models.ForeignKey(
        Turno,
        on_delete=models.CASCADE,
        related_name="reservas",
        verbose_name=_("Turno"),
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.CONFIRMADA,
        verbose_name=_("Estado"),
    )
    tipo_reserva = models.CharField(
        max_length=10,
        choices=TipoReserva.choices,
        default=TipoReserva.INDIVIDUAL,
        verbose_name=_("Tipo de reserva"),
        help_text=_("Indica si esta reserva es parte de una serie mensual o es individual."),
    )
    # Referencia al grupo mensual (agrupa las reservas de una misma serie)
    grupo_mensual = models.ForeignKey(
        "GrupoReservaMensual",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="reservas",
        verbose_name=_("Grupo mensual"),
    )
    fecha_reserva = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Fecha de reserva"),
    )
    fecha_cancelacion = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("Fecha de cancelación"),
    )

    # ── Gancho para pagos futuros ─────────────────────────────────────────────
    # precio_abonado = models.DecimalField(
    #     max_digits=8, decimal_places=2,
    #     null=True, blank=True,
    #     verbose_name=_("Precio abonado"),
    # )
    # referencia_pago = models.CharField(
    #     max_length=100,
    #     blank=True,
    #     verbose_name=_("Referencia de pago"),
    # )
    # medio_pago = models.CharField(
    #     max_length=30,
    #     blank=True,
    #     verbose_name=_("Medio de pago"),
    # )

    class Meta:
        verbose_name        = _("Reserva")
        verbose_name_plural = _("Reservas")
        # Un usuario no puede tener dos reservas activas para el mismo turno
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "turno"],
                condition=models.Q(estado__in=["confirmada", "en_espera"]),
                name="unique_reserva_activa_por_usuario_turno",
            )
        ]
        ordering = ["-fecha_reserva"]

    def __str__(self):
        return f"{self.usuario} – {self.turno} [{self.get_estado_display()}]"

    # ── Lógica de negocio ─────────────────────────────────────────────────────

    def cancelar(self):
        """
        Cancela esta reserva y, si estaba confirmada, promueve al primero
        de la lista de espera del mismo turno.
        """
        if self.estado == self.Estado.CANCELADA:
            raise ValidationError(_("Esta reserva ya fue cancelada."))

        era_confirmada = (self.estado == self.Estado.CONFIRMADA)
        self.estado = self.Estado.CANCELADA
        self.fecha_cancelacion = timezone.now()
        self.save(update_fields=["estado", "fecha_cancelacion"])

        if era_confirmada:
            self._promover_lista_espera()

    def _promover_lista_espera(self):
        """Promueve al primer usuario en lista de espera a CONFIRMADA."""
        siguiente = (
            self.turno.reservas
            .filter(estado=Reserva.Estado.EN_ESPERA)
            .order_by("fecha_reserva")
            .first()
        )
        if siguiente:
            siguiente.estado = Reserva.Estado.CONFIRMADA
            siguiente.save(update_fields=["estado"])


# ── GrupoReservaMensual ───────────────────────────────────────────────────────

class GrupoReservaMensual(models.Model):
    """
    Agrupa las reservas generadas por una reserva mensual.

    Permite al usuario (y al sistema) cancelar todo el grupo de una vez,
    o consultar cuántos turnos del mes se reservaron en bloque.

    Condición de habilitación:
    El día en que se hace la reserva mensual debe estar entre el 1 y el 10
    del mes en curso (DIA_INICIO_VENTANA_MENSUAL – DIA_FIN_VENTANA_MENSUAL).
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="grupos_mensuales",
        verbose_name=_("Usuario"),
    )
    actividad = models.ForeignKey(
        Actividad,
        on_delete=models.PROTECT,
        related_name="grupos_mensuales",
        verbose_name=_("Actividad"),
    )
    # Día de la semana elegido (0=lunes … 5=sábado)
    dia_semana = models.PositiveSmallIntegerField(verbose_name=_("Día de la semana"))
    hora = models.PositiveSmallIntegerField(verbose_name=_("Hora"))
    # Mes y año al que corresponde el bloque
    anio  = models.PositiveSmallIntegerField(verbose_name=_("Año"))
    mes   = models.PositiveSmallIntegerField(verbose_name=_("Mes"))
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha de creación"))

    class Meta:
        verbose_name        = _("Grupo de reserva mensual")
        verbose_name_plural = _("Grupos de reserva mensual")
        ordering            = ["-fecha_creacion"]

    def __str__(self):
        DIAS = [_("Lunes"), _("Martes"), _("Miércoles"), _("Jueves"), _("Viernes"), _("Sábado")]
        dia_nombre = DIAS[self.dia_semana] if self.dia_semana < 6 else "?"
        return (
            f"{self.actividad} – {dia_nombre} {self.hora:02d}:00 "
            f"({self.mes:02d}/{self.anio}) [{self.usuario}]"
        )

    def cancelar_todo(self):
        """Cancela todas las reservas activas del grupo."""
        for reserva in self.reservas.filter(estado__in=[
            Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA
        ]):
            reserva.cancelar()