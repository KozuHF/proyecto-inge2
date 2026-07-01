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

def contar_incumplimientos_no_abonado(usuario, anio: int, mes: int) -> int:
    """
    Clases sueltas (no abono) canceladas en el mes sin haber completado el pago.

    Solo cuenta SEÑADO: una reserva individual siempre se crea con el pago (total
    o seña) aplicado en el mismo momento, así que el único caso real de "clase
    confirmada e impaga" es la que se señó y nunca se completó. PENDIENTE en una
    reserva cancelada solo puede venir de una baja de lista de espera (nunca tuvo
    el cupo confirmado), así que no cuenta.
    """
    return Reserva.objects.filter(
        usuario=usuario,
        grupo_mensual__isnull=True,
        estado=Reserva.Estado.CANCELADA,
        estado_pago=Reserva.EstadoPago.SENADO,
        fecha_cancelacion__year=anio,
        fecha_cancelacion__month=mes,
    ).count()


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
        Reserva.objects
        .filter(
            usuario=usuario,
            grupo_mensual__isnull=True,
            estado=Reserva.Estado.CANCELADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            fecha_cancelacion__year=ahora.year,
            fecha_cancelacion__month=ahora.month,
        )
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
