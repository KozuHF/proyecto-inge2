"""
Lista de espera con invitación por rol.

Cuando se libera un cupo de un turno lleno, en vez de promover directo al primero
de la cola se le **ofrece** el lugar al siguiente candidato mediante una
invitación por mail (`InvitacionCupo`). El candidato tiene un plazo para aceptar
(y pagar) o rechazar; si vence o rechaza, el cupo pasa al siguiente.

Prioridad de la cola (por turno): primero los clientes **abonados de esa
actividad** (orden de llegada), después los no abonados (orden de llegada).

La expiración se maneja de forma combinada:
- *lazy*: las vistas llaman `procesar_si_vencida()` antes de operar;
- *batch*: el command `procesar_invitaciones_vencidas` llama
  `expirar_invitaciones_vencidas()` periódicamente.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import GrupoReservaMensual, InvitacionCupo, Reserva, Turno

logger = logging.getLogger(__name__)


# ── Selección de candidato ────────────────────────────────────────────────────

def _es_abonado_para_actividad(usuario, actividad) -> bool:
    """True si el usuario tiene un abono mensual activo en esa actividad."""
    return GrupoReservaMensual.objects.filter(
        usuario=usuario,
        actividad=actividad,
        reservas__estado__in=[
            Reserva.Estado.CONFIRMADA,
            Reserva.Estado.EN_ESPERA,
            Reserva.Estado.INVITADO,
        ],
    ).exists()


def _siguiente_candidato(turno: Turno):
    """
    Primer candidato de la lista de espera del turno: abonados de la actividad
    primero (FIFO por fecha de reserva), luego no abonados (FIFO).
    """
    from . import suspensiones

    espera = [
        r for r in (
            turno.reservas
            .filter(estado=Reserva.Estado.EN_ESPERA, usuario__suspendido=False)
            .select_related("usuario")
            .order_by("fecha_reserva")
        )
        if suspensiones.suspension_activa_abonado(r.usuario, turno.actividad) is None
    ]
    if not espera:
        return None
    abonados = [r for r in espera if _es_abonado_para_actividad(r.usuario, turno.actividad)]
    if abonados:
        return abonados[0]
    return espera[0]


# ── Ofrecer cupos ─────────────────────────────────────────────────────────────

@transaction.atomic
def ofrecer_cupo_siguiente(turno: Turno) -> int:
    """
    Ofrece todos los cupos libres del turno a la lista de espera, creando una
    invitación por cada cupo. Devuelve la cantidad de invitaciones creadas.

    Idempotente respecto a los cupos congelados: un INVITADO ya ocupa cupo, así
    que no se le ofrece de nuevo el mismo lugar a otra persona.
    """
    turno = Turno.objects.select_for_update().get(pk=turno.pk)
    creadas = 0
    while turno.cupos_libres > 0:
        candidato = _siguiente_candidato(turno)
        if candidato is None:
            break
        candidato.estado = Reserva.Estado.INVITADO
        candidato.save(update_fields=["estado"])
        turno = candidato.turno
        clase_inicio = timezone.make_aware(
            __import__("datetime").datetime(
                turno.fecha.year, turno.fecha.month, turno.fecha.day, turno.hora, 0
            )
        )
        invitacion = InvitacionCupo.objects.create(
            reserva=candidato,
            fecha_vencimiento=clase_inicio,
        )
        _enviar_invitacion(invitacion)
        creadas += 1
    return creadas


def _enviar_invitacion(invitacion: InvitacionCupo):
    from .notificaciones import enviar_invitacion_cupo
    enviar_invitacion_cupo(invitacion)


# ── Respuesta del candidato ───────────────────────────────────────────────────

def procesar_si_vencida(invitacion: InvitacionCupo) -> bool:
    """
    Lazy-check: si la invitación ya venció, la marca VENCIDA, libera el cupo y lo
    ofrece al siguiente. Devuelve True si estaba vencida.
    """
    if invitacion.esta_vencida:
        _vencer(invitacion)
        return True
    return False


def aceptar(invitacion: InvitacionCupo) -> Reserva:
    """
    Valida que la invitación siga vigente. NO confirma todavía: la reserva queda
    en INVITADO y la confirmación ocurre cuando se aprueba el pago. Devuelve la
    reserva a pagar. Si venció o ya no está disponible, lanza ValidationError.
    """
    if procesar_si_vencida(invitacion):
        raise ValidationError(
            _("La invitación venció. El cupo se le ofreció al siguiente de la lista.")
        )
    if invitacion.estado != InvitacionCupo.Estado.PENDIENTE:
        raise ValidationError(_("Esta invitación ya no está disponible."))

    from . import suspensiones

    reserva = invitacion.reserva
    if not suspensiones.usuario_puede_reservar_actividad(reserva.usuario, reserva.turno.actividad):
        raise ValidationError(
            _("Tu cuenta está suspendida. Contactá al club para más información.")
        )
    return reserva


@transaction.atomic
def rechazar(invitacion: InvitacionCupo) -> None:
    """Rechaza la invitación, libera el cupo y lo ofrece al siguiente."""
    invitacion = InvitacionCupo.objects.select_for_update().get(pk=invitacion.pk)
    if invitacion.estado != InvitacionCupo.Estado.PENDIENTE:
        raise ValidationError(_("Esta invitación ya no está disponible."))
    invitacion.estado = InvitacionCupo.Estado.RECHAZADA
    invitacion.fecha_respuesta = timezone.now()
    invitacion.save(update_fields=["estado", "fecha_respuesta"])
    # cancelar() pone la reserva en CANCELADA y ofrece el cupo al siguiente.
    invitacion.reserva.cancelar()


def confirmar_por_pago(reserva: Reserva) -> None:
    """
    Marca como ACEPTADA la invitación de una reserva que acaba de pagar y la pasa
    a CONFIRMADA. Lo llama el flujo de pago al aprobarse el cobro de un INVITADO.
    """
    invitacion = getattr(reserva, "invitacion", None)
    if invitacion and invitacion.estado == InvitacionCupo.Estado.PENDIENTE:
        invitacion.estado = InvitacionCupo.Estado.ACEPTADA
        invitacion.fecha_respuesta = timezone.now()
        invitacion.save(update_fields=["estado", "fecha_respuesta"])
    reserva.estado = Reserva.Estado.CONFIRMADA
    reserva.save(update_fields=["estado"])


def _vencer(invitacion: InvitacionCupo) -> None:
    invitacion.estado = InvitacionCupo.Estado.VENCIDA
    invitacion.fecha_respuesta = timezone.now()
    invitacion.save(update_fields=["estado", "fecha_respuesta"])
    reserva = invitacion.reserva
    # Defensa ante carreras: si la reserva ya fue cancelada por otra vía,
    # no volvemos a cancelarla (cancelar() lanzaría error).
    if reserva.estado != Reserva.Estado.CANCELADA:
        reserva.cancelar()  # libera el cupo y ofrece al siguiente


# ── Expiración batch (management command) ─────────────────────────────────────

def expirar_invitaciones_vencidas() -> int:
    """Vence todas las invitaciones pendientes cuyo plazo ya pasó. Devuelve cuántas."""
    pendientes = InvitacionCupo.objects.filter(
        estado=InvitacionCupo.Estado.PENDIENTE,
        fecha_vencimiento__lte=timezone.now(),
    ).values_list("pk", flat=True)

    n = 0
    for pk in list(pendientes):
        with transaction.atomic():
            inv = InvitacionCupo.objects.select_for_update().select_related(
                "reserva", "reserva__turno"
            ).get(pk=pk)
            if inv.estado != InvitacionCupo.Estado.PENDIENTE:
                continue
            if inv.fecha_vencimiento > timezone.now():
                continue
            _vencer(inv)
            n += 1
    if n:
        logger.info("Invitaciones vencidas procesadas: %d", n)
    return n


# ── Aviso al admin ────────────────────────────────────────────────────────────

def chequear_umbral_admin() -> None:
    """
    Avisa al admin cuando el total de clientes en lista de espera del sistema
    alcanza exactamente el umbral configurado (evita repetir el mail en 11, 12…).
    """
    total = Reserva.objects.filter(estado=Reserva.Estado.EN_ESPERA).count()
    if total == settings.UMBRAL_AVISO_LISTA_ESPERA:
        from .notificaciones import enviar_aviso_admin_lista_espera
        enviar_aviso_admin_lista_espera(total)
