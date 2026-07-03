"""
Suspensiones de clientes.

Hay dos mecanismos independientes:

- Abonados: se suspenden POR DEPORTE (no afecta a sus otros abonos ni a
  turnos sueltos de otras actividades) si no pagan el abono completo al día
  11 (`SuspensionAbonado.Motivo.PLAZO_VENCIDO`). Se levanta pagando las clases
  del 1 al 10 que quedaron impagas + 5 % de recargo.

- No abonados: se suspenden GLOBALMENTE (`Usuario.suspendido`) al acumular 3
  clases sueltas SEÑADAS y nunca completadas en el mismo mes, sin importar el
  deporte. No pueden reservar turnos sueltos de ningún deporte hasta pagar lo
  adeudado (el restante de esas 3 clases) + 5 % de recargo.

Los contadores son mensuales por naturaleza (se cuenta solo lo del mes en
curso): un usuario que ya está suspendido simplemente no vuelve a ser
evaluado hasta que se levante la suspensión, así que el cambio de mes no la
levanta por sí solo.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Reserva, SuspensionAbonado

RECARGO_LEVANTAMIENTO = Decimal("1.05")
UMBRAL_INCUMPLIMIENTOS_NO_ABONADO = 3


# ── Conteo ─────────────────────────────────────────────────────────────────────

def _qs_incumplimientos_no_abonado(usuario, anio: int, mes: int):
    """Reservas señadas canceladas por no-show que cuentan para la suspensión."""
    return Reserva.objects.filter(
        usuario=usuario,
        grupo_mensual__isnull=True,
        estado=Reserva.Estado.CANCELADA,
        estado_pago=Reserva.EstadoPago.SENADO,
        incumplimiento_no_abonado=True,
        fecha_cancelacion__year=anio,
        fecha_cancelacion__month=mes,
    )


def contar_incumplimientos_no_abonado(usuario, anio: int, mes: int) -> int:
    """
    Clases sueltas señadas canceladas en el mes por no asistir sin completar el pago.
    """
    return _qs_incumplimientos_no_abonado(usuario, anio, mes).count()


@transaction.atomic
def cancelar_por_ausencia_impaga(reserva: Reserva) -> bool:
    """
    Cancela una reserva individual impaga cuya clase ya terminó y el cliente
    no asistió. La seña se retiene. Si estaba señada, cuenta como incumplimiento
    para la suspensión global de no abonados. No ofrece el cupo en lista de espera.
    """
    from .cancelacion_clase import _cancelar_reserva_sin_lista_espera

    if reserva.estado == Reserva.Estado.CANCELADA:
        return False
    if reserva.grupo_mensual_id is not None:
        return False
    if reserva.estado_pago not in (
        Reserva.EstadoPago.PENDIENTE,
        Reserva.EstadoPago.SENADO,
    ):
        return False

    era_señada = reserva.estado_pago == Reserva.EstadoPago.SENADO
    _cancelar_reserva_sin_lista_espera(reserva)

    if era_señada:
        reserva.incumplimiento_no_abonado = True
        reserva.save(update_fields=["incumplimiento_no_abonado"])
        verificar_suspension_no_abonado(reserva.usuario)
    return True


# ── Suspensión de abonados (por deporte) ───────────────────────────────────────

def suspension_activa_abonado(usuario, actividad) -> SuspensionAbonado | None:
    return SuspensionAbonado.objects.filter(
        usuario=usuario, actividad=actividad, activa=True
    ).first()


@transaction.atomic
def suspender_abonado(usuario, actividad, motivo: str, monto_adeudado: Decimal) -> SuspensionAbonado:
    existente = suspension_activa_abonado(usuario, actividad)
    if existente:
        return existente
    return SuspensionAbonado.objects.create(
        usuario=usuario,
        actividad=actividad,
        motivo=motivo,
        monto_adeudado=(monto_adeudado * RECARGO_LEVANTAMIENTO).quantize(Decimal("0.01")),
    )


def verificar_suspension_no_abonado(usuario) -> bool:
    """
    Llamar después de cancelar/vencer una clase suelta impaga. Si llegó al
    umbral en el mes, suspende globalmente al usuario (si no lo estaba ya).
    Devuelve True si quedó (o ya estaba) suspendido.
    """
    if usuario.suspendido:
        return True

    ahora = timezone.localtime(timezone.now())
    cantidad = contar_incumplimientos_no_abonado(usuario, ahora.year, ahora.month)
    if cantidad < UMBRAL_INCUMPLIMIENTOS_NO_ABONADO:
        return False

    ultimas = (
        _qs_incumplimientos_no_abonado(usuario, ahora.year, ahora.month)
        .order_by("-fecha_cancelacion")[:UMBRAL_INCUMPLIMIENTOS_NO_ABONADO]
    )
    monto = sum((r.monto_saldo for r in ultimas), Decimal("0"))

    usuario.suspendido = True
    usuario.monto_adeudado_suspension = (monto * RECARGO_LEVANTAMIENTO).quantize(Decimal("0.01"))
    usuario.save(update_fields=["suspendido", "monto_adeudado_suspension"])
    return True


# ── Consultas de acceso ─────────────────────────────────────────────────────────

def usuario_puede_reservar_actividad(usuario, actividad) -> bool:
    """
    False si el usuario está suspendido globalmente (no abonado) o
    específicamente suspendido como abonado de esa actividad.
    """
    if usuario.suspendido:
        return False
    return suspension_activa_abonado(usuario, actividad) is None


def suspensiones_activas_de(usuario):
    """Todas las suspensiones de abono activas del usuario (para mostrarlas en Mi cuenta)."""
    return SuspensionAbonado.objects.filter(usuario=usuario, activa=True).select_related("actividad")


# ── Levantamiento ────────────────────────────────────────────────────────────────

@transaction.atomic
def levantar_suspension_abonado(suspension: SuspensionAbonado):
    suspension.levantar()


@transaction.atomic
def levantar_suspension_no_abonado(usuario):
    usuario.suspendido = False
    usuario.monto_adeudado_suspension = None
    usuario.save(update_fields=["suspendido", "monto_adeudado_suspension"])
