import calendar
import uuid
from datetime import date as _date
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad


# ── Constantes de negocio ─────────────────────────────────────────────────────

HORA_APERTURA  = 8
HORA_CIERRE    = 22
DIAS_HABILES   = [0, 1, 2, 3, 4, 5]  # Lunes=0 … Sábado=5 (domingo=6 cerrado)
HORAS_VALIDAS  = list(range(HORA_APERTURA, HORA_CIERRE))

FERIADOS_INAMOVIBLES = {
    (1, 1),    # Año Nuevo
    (3, 24),   # Día de la Memoria
    (4, 2),    # Día de las Malvinas
    (5, 1),    # Día del Trabajador
    (5, 25),   # Revolución de Mayo
    (6, 20),   # Belgrano
    (7, 9),    # Día de la Independencia
    (12, 8),   # Inmaculada Concepción
    (12, 25),  # Navidad
}

# Modos del wizard de reserva (sesión)
MODO_TURNO_UNICO = "unico"
MODO_VARIOS_TURNOS = "varios"

DIAS_SEMANA_CHOICES = [
    (0, _("Lunes")),
    (1, _("Martes")),
    (2, _("Miércoles")),
    (3, _("Jueves")),
    (4, _("Viernes")),
    (5, _("Sábado")),
]


def _validar_dia_habil(fecha: "datetime.date"):
    if fecha.weekday() not in DIAS_HABILES:
        raise ValidationError(_("El establecimiento no abre los domingos."))
    if (fecha.month, fecha.day) in FERIADOS_INAMOVIBLES:
        raise ValidationError(_("El establecimiento permanece cerrado por feriado nacional."))


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


# Máximo que un cliente puede reservar hacia adelante: un mes a partir de hoy.
def fecha_limite_reserva():
    """Última fecha reservable: un mes a partir de hoy (abonado o no)."""
    hoy = timezone.now().date()
    mes = hoy.month % 12 + 1
    anio = hoy.year + (1 if hoy.month == 12 else 0)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return _date(anio, mes, min(hoy.day, ultimo_dia))


def _validar_dentro_de_limite(fecha):
    if fecha > fecha_limite_reserva():
        raise ValidationError(_("Solo se puede reservar hasta un mes a partir de hoy."))


# ── HorarioDisponible ────────────────────────────────────────────────────────

class HorarioDisponible(models.Model):
    """
    Define un bloque horario recurrente para una actividad en un día de la semana.

    El admin crea estos registros para indicar en qué días y horarios existe
    un turno disponible para reservar. Cada instancia genera automáticamente
    los objetos Turno correspondientes al mes que se está reservando.

    Reglas de negocio:
    - Un turno siempre dura exactamente 1 hora.
    - No puede haber dos horarios de la misma actividad que se superpongan
      en el mismo día de la semana (unicidad: actividad + dia_semana + hora).
    - El horario debe estar dentro del rango [HORA_APERTURA, HORA_CIERRE).
    """

    actividad = models.ForeignKey(
        Actividad,
        on_delete=models.CASCADE,
        related_name="horarios_disponibles",
        verbose_name=_("Actividad"),
    )
    dia_semana = models.PositiveSmallIntegerField(
        choices=DIAS_SEMANA_CHOICES,
        verbose_name=_("Día de la semana"),
    )
    hora = models.PositiveSmallIntegerField(
        verbose_name=_("Hora de inicio"),
        help_text=_("Hora entera. El turno dura 1 hora."),
    )
    cupos = models.PositiveIntegerField(
        verbose_name=_("Cupos"),
        validators=[MinValueValidator(1)],
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Precio"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    activo = models.BooleanField(
        default=True,
        verbose_name=_("Activo"),
        help_text=_("Desactivar impide que se generen nuevos turnos, pero no cancela los existentes."),
    )

    class Meta:
        verbose_name        = _("Horario disponible")
        verbose_name_plural = _("Horarios disponibles")
        unique_together     = [("actividad", "dia_semana", "hora")]
        ordering            = ["dia_semana", "hora", "actividad"]

    def __str__(self):
        dia = dict(DIAS_SEMANA_CHOICES).get(self.dia_semana, self.dia_semana)
        return f"{self.actividad} – {dia} {self.hora:02d}:00"

    def clean(self):
        _validar_hora(self.hora)
        if self.dia_semana not in dict(DIAS_SEMANA_CHOICES):
            raise ValidationError(_("El día de la semana no es válido."))

    def cupos_efectivos(self) -> int:
        """Retorna los cupos definidos en el horario, o los de la actividad como fallback."""
        if self.cupos is not None:
            return self.cupos
        return self.actividad.cupos


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
    precio_override = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("Precio"),
        help_text=_("Si se completa, reemplaza el precio de la actividad."),
    )

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
        # Validar solapamiento: no puede haber otro turno de la misma actividad
        # que ocupe el mismo bloque horario en la misma fecha.
        # Dado que cada turno dura exactamente 1 hora, solapamiento ocurre solo
        # cuando coinciden actividad + fecha + hora (ya cubierto por unique_together),
        # pero también hay que verificar que no exista un HorarioDisponible duplicado
        # que pudiera haberse colado. La unicidad real la garantiza unique_together;
        # este bloque es para dar un mensaje de error legible desde el admin/forms.
        conflicto_qs = Turno.objects.filter(
            actividad=self.actividad,
            fecha=self.fecha,
            hora=self.hora,
        )
        if self.pk:
            conflicto_qs = conflicto_qs.exclude(pk=self.pk)
        if conflicto_qs.exists():
            raise ValidationError(
                _("Ya existe un turno de %(actividad)s el %(fecha)s a las %(hora)02d:00. "
                  "Solo puede haber un turno por actividad en cada franja horaria.")
                % {"actividad": self.actividad, "fecha": self.fecha, "hora": self.hora}
            )
        if self.pk:
            ocupados = self.cupos_ocupados
            if self.cupos < ocupados:
                raise ValidationError(
                    _("No podés reducir los cupos por debajo de las reservas ya confirmadas (%(ocupados)d).")
                    % {"ocupados": ocupados}
                )

    def ofrecer_cupos_libres(self):
        """
        Ofrece los cupos libres a la lista de espera (con prioridad por rol),
        creando una invitación por cada cupo. No promueve directo: ver
        `apps.turnos.lista_espera.ofrecer_cupo_siguiente`.
        """
        from .lista_espera import ofrecer_cupo_siguiente
        ofrecer_cupo_siguiente(self)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if not is_new:
            self.ofrecer_cupos_libres()

    # ── Propiedades calculadas ────────────────────────────────────────────────

    @property
    def cupos_totales(self) -> int:
        return self.cupos

    @property
    def reservas_confirmadas(self):
        return self.reservas.filter(estado=Reserva.Estado.CONFIRMADA)

    @property
    def cupos_ocupados(self) -> int:
        # Un INVITADO tiene el cupo congelado mientras decide, así que cuenta
        # como ocupado igual que una reserva confirmada.
        return self.reservas.filter(
            estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.INVITADO]
        ).count()

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
    @property
    def precio_efectivo(self):
        return self.precio_override if self.precio_override is not None else self.actividad.precio_turno


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
        INVITADO   = "invitado",   _("Invitado (esperá confirmación)")
        CANCELADA  = "cancelada",  _("Cancelada")

    class TipoReserva(models.TextChoices):
        INDIVIDUAL = "individual", _("Turno único")
        VARIOS     = "varios",     _("Abonado mensual")
        MENSUAL    = "mensual",    _("Abonado mensual")  # reservas antiguas

    class EstadoPago(models.TextChoices):
        PENDIENTE = "pendiente", _("Pago pendiente")
        SENADO    = "senado",    _("Señado")
        PAGADO    = "pagado",    _("Pagado")

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

    estado_pago = models.CharField(
        max_length=10,
        choices=EstadoPago.choices,
        default=EstadoPago.PENDIENTE,
        verbose_name=_("Estado de pago"),
    )
    precio_abonado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Precio abonado"),
    )
    referencia_pago = models.CharField(
        max_length=40,
        blank=True,
        verbose_name=_("Referencia de pago"),
    )

    class Meta:
        verbose_name        = _("Reserva")
        verbose_name_plural = _("Reservas")
        # Un usuario no puede tener dos reservas activas para el mismo turno
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "turno"],
                condition=models.Q(estado__in=["confirmada", "en_espera", "invitado"]),
                name="unique_reserva_activa_por_usuario_turno",
            )
        ]
        ordering = ["-fecha_reserva"]

    def __str__(self):
        return f"{self.usuario} – {self.turno} [{self.get_estado_display()}]"

    @property
    def esta_pagada(self) -> bool:
        return self.estado_pago == self.EstadoPago.PAGADO

    @property
    def esta_senada(self) -> bool:
        return self.estado_pago == self.EstadoPago.SENADO

    @property
    def es_abonado_mensual(self) -> bool:
        return (
            self.grupo_mensual_id is not None
            and self.tipo_reserva in (self.TipoReserva.VARIOS, self.TipoReserva.MENSUAL)
        )

    @property
    def tipo_abono_display(self) -> str:
        if self.es_abonado_mensual:
            return str(_("Abonado mensual"))
        return str(_("Turno único"))

    @property
    def puede_pagar(self) -> bool:
        if self.es_abonado_mensual:
            return False
        # Solo se paga una reserva confirmada (completar saldo) o invitada (aceptar
        # el cupo). Estando EN_ESPERA no se paga: anotarse es gratis hasta que se
        # libere un cupo y se acepte la invitación.
        if self.estado not in (self.Estado.CONFIRMADA, self.Estado.INVITADO):
            return False
        return self.estado_pago in (self.EstadoPago.PENDIENTE, self.EstadoPago.SENADO)

    @property
    def monto_total(self):
        from .penalidad_cancelaciones import precio_turno_con_regla

        base = self.turno.precio_efectivo
        if self.grupo_mensual_id:
            g = self.grupo_mensual
            return precio_turno_con_regla(
                base, g.regla_cobro, self.usuario, g.anio, g.mes
            )
        return base

    @property
    def monto_sena(self):
        from decimal import Decimal
        return (self.monto_total * Decimal("0.5")).quantize(Decimal("0.01"))

    @property
    def monto_saldo(self):
        from decimal import Decimal
        abonado = self.precio_abonado or Decimal("0")
        return (self.monto_total - abonado).quantize(Decimal("0.01"))

    # ── Lógica de negocio ─────────────────────────────────────────────────────

    def cancelar(self):
        """
        Cancela esta reserva y, si liberó un cupo confirmado, le ofrece el lugar
        al siguiente de la lista de espera mediante una invitación por mail
        (ver `apps.turnos.lista_espera.ofrecer_cupo_siguiente`).
        """
        if self.estado == self.Estado.CANCELADA:
            raise ValidationError(_("Esta reserva ya fue cancelada."))

        libero_cupo = self.estado in (self.Estado.CONFIRMADA, self.Estado.INVITADO)
        self.estado = self.Estado.CANCELADA
        self.fecha_cancelacion = timezone.now()
        self.save(update_fields=["estado", "fecha_cancelacion"])

        if libero_cupo:
            # Si la reserva tenía una invitación pendiente (se cancela por otra
            # vía, ej. suspensión), la cerramos para no dejarla huérfana.
            invitacion = InvitacionCupo.objects.filter(
                reserva=self, estado=InvitacionCupo.Estado.PENDIENTE
            ).first()
            if invitacion:
                invitacion.estado = InvitacionCupo.Estado.VENCIDA
                invitacion.fecha_respuesta = timezone.now()
                invitacion.save(update_fields=["estado", "fecha_respuesta"])

            from .lista_espera import ofrecer_cupo_siguiente
            ofrecer_cupo_siguiente(self.turno)


# ── GrupoReservaMensual ───────────────────────────────────────────────────────

class GrupoReservaMensual(models.Model):
    """
    Agrupa las reservas de un mismo checkout «varios turnos».

    Permite cancelar todo el bloque de una vez desde Mis reservas.
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
    regla_cobro = models.CharField(
        max_length=20,
        default="primera_quincena",
        verbose_name=_("Regla de cobro"),
    )
    descuento_porcentaje = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name=_("Descuento (%)"),
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha de creación"))

    class Meta:
        verbose_name        = _("Abonado mensual")
        verbose_name_plural = _("Abonados mensuales")
        ordering            = ["-fecha_creacion"]

    def reservas_activas(self):
        return self.reservas.filter(
            estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA]
        )

    @property
    def cantidad_turnos_activos(self) -> int:
        return self.reservas_activas().count()

    @property
    def monto_total_grupo(self):
        from decimal import Decimal
        total = sum((r.monto_total for r in self.reservas_activas()), Decimal("0"))
        return total.quantize(Decimal("0.01"))

    @property
    def monto_abonado_grupo(self):
        from decimal import Decimal
        total = sum(
            ((r.precio_abonado or Decimal("0")) for r in self.reservas_activas()),
            Decimal("0"),
        )
        return total.quantize(Decimal("0.01"))

    @property
    def monto_saldo_grupo(self):
        from decimal import Decimal
        return (self.monto_total_grupo - self.monto_abonado_grupo).quantize(Decimal("0.01"))

    @property
    def estado_pago_agregado(self):
        estados = set(self.reservas_activas().values_list("estado_pago", flat=True))
        if not estados:
            return None
        if len(estados) == 1:
            return estados.pop()
        if Reserva.EstadoPago.PENDIENTE in estados:
            return Reserva.EstadoPago.PENDIENTE
        if Reserva.EstadoPago.SENADO in estados:
            return Reserva.EstadoPago.SENADO
        return Reserva.EstadoPago.PAGADO

    @property
    def esta_pagado_grupo(self) -> bool:
        return self.estado_pago_agregado == Reserva.EstadoPago.PAGADO

    @property
    def esta_senado_grupo(self) -> bool:
        return self.estado_pago_agregado == Reserva.EstadoPago.SENADO

    @property
    def puede_pagar_grupo(self) -> bool:
        from .abono_mensual import plazo_pago_vencido

        if plazo_pago_vencido(self):
            return False
        return self.estado_pago_agregado in (
            Reserva.EstadoPago.PENDIENTE,
            Reserva.EstadoPago.SENADO,
        )

    @property
    def tiene_descuento(self) -> bool:
        return self.descuento_porcentaje > 0

    @property
    def permite_pago_sena(self) -> bool:
        from .abono_mensual import permite_pago_sena

        return permite_pago_sena(self.regla_cobro)

    @property
    def incluye_turnos_dia_1_a_10(self) -> bool:
        from .abono_mensual import abono_incluye_turnos_dia_1_a_10

        fechas = [r.turno.fecha for r in self.reservas_activas().select_related("turno")]
        return abono_incluye_turnos_dia_1_a_10(fechas)

    @property
    def aviso_plazo_pago(self) -> str | None:
        from .abono_mensual import texto_tiempo_restante_pago

        if not self.incluye_turnos_dia_1_a_10 or self.esta_pagado_grupo:
            return None
        return texto_tiempo_restante_pago(self.anio, self.mes)

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


class CancelacionAbonoMensual(models.Model):
    """
    Registro de cancelación de un turno de abono mensual.
    Cuenta para la penalización del 20 % (3+ en un mes → sin descuento el mes siguiente).
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cancelaciones_abono_mensual",
        verbose_name=_("Usuario"),
    )
    reserva = models.ForeignKey(
        Reserva,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelaciones_abono_registradas",
        verbose_name=_("Reserva"),
    )
    anio_cancelacion = models.PositiveSmallIntegerField(verbose_name=_("Año"))
    mes_cancelacion = models.PositiveSmallIntegerField(verbose_name=_("Mes"))
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Cancelación abono mensual")
        verbose_name_plural = _("Cancelaciones abono mensual")
        ordering = ["-fecha_registro"]
        indexes = [
            models.Index(
                fields=["usuario", "anio_cancelacion", "mes_cancelacion"],
                name="cancel_abono_usuario_mes_idx",
            ),
        ]

    def __str__(self):
        return f"{self.usuario} – {self.mes_cancelacion:02d}/{self.anio_cancelacion}"


# ── SuspensionAbonado ─────────────────────────────────────────────────────────

class SuspensionAbonado(models.Model):
    """
    Suspensión de un abonado en una actividad puntual (no afecta a sus otros
    deportes). Motivo: no pagó el abono completo al día 11.

    Mientras esté activa, el usuario no puede reservar ni abono mensual ni
    turnos sueltos de esa actividad. Se levanta pagando `monto_adeudado`
    (incluye el 5 % de recargo) desde Mi cuenta.
    """

    class Motivo(models.TextChoices):
        PLAZO_VENCIDO = "plazo_vencido", _("Abono impago al día 11")

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="suspensiones_abonado",
        verbose_name=_("Usuario"),
    )
    actividad = models.ForeignKey(
        Actividad,
        on_delete=models.CASCADE,
        related_name="suspensiones_abonado",
        verbose_name=_("Actividad"),
    )
    motivo = models.CharField(
        max_length=20,
        choices=Motivo.choices,
        verbose_name=_("Motivo"),
    )
    monto_adeudado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Monto a pagar para levantar la suspensión"),
    )
    activa = models.BooleanField(default=True, verbose_name=_("Activa"))
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha de suspensión"))
    fecha_levantamiento = models.DateTimeField(null=True, blank=True, verbose_name=_("Fecha de levantamiento"))

    class Meta:
        verbose_name = _("Suspensión de abonado")
        verbose_name_plural = _("Suspensiones de abonado")
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return f"{self.usuario} – {self.actividad} ({self.get_motivo_display()})"

    def levantar(self):
        self.activa = False
        self.fecha_levantamiento = timezone.now()
        self.save(update_fields=["activa", "fecha_levantamiento"])


# ── InvitacionCupo ────────────────────────────────────────────────────────────

class InvitacionCupo(models.Model):
    """
    Oferta de un cupo liberado al siguiente de la lista de espera de un turno.

    Cuando se libera un cupo, la reserva del candidato pasa a INVITADO y se crea
    esta invitación con un plazo (`fecha_vencimiento`). El candidato tiene hasta
    ese momento para aceptar (y pagar) o rechazar. Si vence o rechaza, el cupo se
    le ofrece al siguiente.
    """

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", _("Pendiente")
        ACEPTADA  = "aceptada",  _("Aceptada")
        RECHAZADA = "rechazada", _("Rechazada")
        VENCIDA   = "vencida",   _("Vencida")

    reserva = models.OneToOneField(
        Reserva,
        on_delete=models.CASCADE,
        related_name="invitacion",
        verbose_name=_("Reserva"),
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name=_("Token"),
    )
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        verbose_name=_("Estado"),
    )
    fecha_envio = models.DateTimeField(auto_now_add=True, verbose_name=_("Fecha de envío"))
    fecha_vencimiento = models.DateTimeField(verbose_name=_("Fecha de vencimiento"))
    fecha_respuesta = models.DateTimeField(null=True, blank=True, verbose_name=_("Fecha de respuesta"))

    class Meta:
        verbose_name = _("Invitación de cupo")
        verbose_name_plural = _("Invitaciones de cupo")
        ordering = ["-fecha_envio"]

    def __str__(self):
        return f"Invitación {self.reserva.usuario} – {self.reserva.turno} [{self.get_estado_display()}]"

    @property
    def esta_vigente(self) -> bool:
        return self.estado == self.Estado.PENDIENTE and timezone.now() < self.fecha_vencimiento

    @property
    def esta_vencida(self) -> bool:
        return self.estado == self.Estado.PENDIENTE and timezone.now() >= self.fecha_vencimiento

    @property
    def segundos_restantes(self) -> int:
        restante = (self.fecha_vencimiento - timezone.now()).total_seconds()
        return max(0, int(restante))
