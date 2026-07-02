"""
Cancelación de una clase puntual (un turno) por parte del administrador.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.creditos import services as creditos_services

from .models import InvitacionCupo, Reserva, Turno

DIAS_SEMANA = [
    _("Lunes"), _("Martes"), _("Miércoles"), _("Jueves"),
    _("Viernes"), _("Sábado"), _("Domingo"),
]


class TipoCompensacion(str, Enum):
    CREDITO = "credito"
    REEMBOLSO_SENA = "reembolso_sena"
    NINGUNA = "ninguna"


@dataclass
class ImpactoReserva:
    reserva: Reserva
    nombre_usuario: str
    compensacion: TipoCompensacion
    detalle: str


def inicio_turno(fecha: date, hora: int) -> datetime:
    naive = datetime.combine(fecha, time(hour=hora, minute=0))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def validar_fecha_hora_futura(fecha: date, hora: int) -> None:
    if inicio_turno(fecha, hora) <= timezone.now():
        raise ValidationError(
            _("La fecha y el horario deben ser posteriores al momento actual.")
        )


def buscar_turno_clase(actividad, fecha: date, hora: int) -> Turno | None:
    try:
        return (
            Turno.objects
            .select_related("actividad")
            .prefetch_related("reservas__usuario", "reservas__grupo_mensual")
            .get(actividad=actividad, fecha=fecha, hora=hora)
        )
    except Turno.DoesNotExist:
        return None


def _estados_activos():
    return [
        Reserva.Estado.CONFIRMADA,
        Reserva.Estado.EN_ESPERA,
        Reserva.Estado.INVITADO,
    ]


def reservas_activas_turno(turno: Turno) -> list[Reserva]:
    return list(
        turno.reservas
        .filter(estado__in=_estados_activos())
        .select_related("usuario", "turno__actividad", "grupo_mensual")
        .order_by("usuario__apellido", "usuario__nombre")
    )


def clasificar_compensacion(reserva: Reserva) -> tuple[TipoCompensacion, str]:
    actividad = reserva.turno.actividad.get_nombre_display()
    if (
        reserva.estado_pago == Reserva.EstadoPago.PAGADO
        or reserva.es_abonado_mensual
    ):
        return (
            TipoCompensacion.CREDITO,
            _("1 crédito de %(deporte)s") % {"deporte": actividad},
        )
    if reserva.estado_pago == Reserva.EstadoPago.SENADO:
        monto = reserva.precio_abonado or Decimal("0")
        return (
            TipoCompensacion.REEMBOLSO_SENA,
            _("Reintegro de seña ($%(monto)s)") % {"monto": monto},
        )
    return TipoCompensacion.NINGUNA, _("Sin cargo")


def analizar_cancelacion(turno: Turno) -> list[ImpactoReserva]:
    impactos = []
    for reserva in reservas_activas_turno(turno):
        compensacion, detalle = clasificar_compensacion(reserva)
        impactos.append(
            ImpactoReserva(
                reserva=reserva,
                nombre_usuario=reserva.usuario.get_full_name(),
                compensacion=compensacion,
                detalle=detalle,
            )
        )
    return impactos


def _cerrar_invitacion_pendiente(reserva: Reserva) -> None:
    invitacion = InvitacionCupo.objects.filter(
        reserva=reserva,
        estado=InvitacionCupo.Estado.PENDIENTE,
    ).first()
    if invitacion:
        invitacion.estado = InvitacionCupo.Estado.VENCIDA
        invitacion.fecha_respuesta = timezone.now()
        invitacion.save(update_fields=["estado", "fecha_respuesta"])


def _cancelar_reserva_sin_lista_espera(reserva: Reserva) -> None:
    if reserva.estado == Reserva.Estado.CANCELADA:
        return
    _cerrar_invitacion_pendiente(reserva)
    reserva.estado = Reserva.Estado.CANCELADA
    reserva.fecha_cancelacion = timezone.now()
    reserva.save(update_fields=["estado", "fecha_cancelacion"])


@transaction.atomic
def ejecutar_cancelacion_clase(turno: Turno) -> list[ImpactoReserva]:
    """
    Cancela el turno, compensa a los inscriptos y envía los avisos por mail.
    No reutiliza Reserva.cancelar() para no ofrecer cupos de una clase que se elimina.
    """
    from .notificaciones import enviar_aviso_cancelacion_clase_por_club

    impactos = analizar_cancelacion(turno)

    for impacto in impactos:
        reserva = impacto.reserva
        if impacto.compensacion == TipoCompensacion.CREDITO:
            creditos_services.otorgar_credito_cancelacion(reserva)
        _cancelar_reserva_sin_lista_espera(reserva)

        monto_reembolso = None
        if impacto.compensacion == TipoCompensacion.REEMBOLSO_SENA:
            monto_reembolso = reserva.precio_abonado or Decimal("0")

        enviar_aviso_cancelacion_clase_por_club(
            reserva,
            impacto.compensacion.value,
            monto_reembolso=monto_reembolso,
        )

    turno.delete()
    return impactos
