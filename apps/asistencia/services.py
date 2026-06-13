"""
Lógica de negocio de asistencia por QR.
"""
import datetime
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.turnos.models import Reserva
from .models import Asistencia

# La asistencia se puede registrar desde 30 min antes del inicio de la clase
# y hasta que la clase termina (los turnos duran 1 hora).
VENTANA_PREVIA_MINUTOS = 30
DURACION_CLASE_MINUTOS = 60


class AsistenciaNoElegible(ValidationError):
    """La reserva no es elegible para asistencia (no pagada / no confirmada)."""


@dataclass
class ResultadoMarcado:
    exito: bool
    estado: str          # "registrada" | "ya_registrada" | "fuera_de_ventana" | "no_elegible"
    mensaje: str
    asistencia: Asistencia | None = None


def ventana_asistencia(turno) -> tuple[datetime.datetime, datetime.datetime]:
    """
    Devuelve (apertura, cierre) de la ventana en la que se puede registrar
    asistencia a un turno: desde 30 min antes del inicio hasta que termina.
    """
    inicio_naive = datetime.datetime.combine(turno.fecha, datetime.time(hour=turno.hora))
    inicio = timezone.make_aware(inicio_naive)
    apertura = inicio - datetime.timedelta(minutes=VENTANA_PREVIA_MINUTOS)
    cierre = inicio + datetime.timedelta(minutes=DURACION_CLASE_MINUTOS)
    return apertura, cierre


def ventana_cerrada(turno) -> bool:
    """True si ya pasó el horario de asistencia (la clase terminó)."""
    _, cierre = ventana_asistencia(turno)
    return timezone.now() > cierre


def qr_disponible(reserva) -> bool:
    """
    Indica si al cliente todavía se le debe mostrar el QR de la reserva.

    Se muestra mientras la reserva sea elegible, el plazo de pago del abono no
    haya vencido y la ventana de asistencia no haya cerrado. Una vez que pasó
    el horario de la clase, el QR ya no sirve y deja de mostrarse.
    """
    return (
        _reserva_elegible(reserva)
        and not _abono_con_plazo_vencido(reserva)
        and not ventana_cerrada(reserva.turno)
    )


def _reserva_elegible(reserva: Reserva) -> bool:
    """
    Reglas de elegibilidad del QR según tipo de reserva:
    - Abonado mensual: elegible desde que reserva (tiene hasta el día 10 del
      mes para pagar el abono).
    - Turno individual: elegible solo con el 100% pagado (señas no alcanzan).
    """
    if reserva.estado != Reserva.Estado.CONFIRMADA:
        return False
    return (
        reserva.estado_pago == Reserva.EstadoPago.PAGADO
        or reserva.es_abonado_mensual
    )


def _abono_con_plazo_vencido(reserva: Reserva) -> bool:
    """
    True si la reserva es de un abono impago cuyo plazo de pago ya venció
    (día 11 en adelante). Chequeo defensivo: la sanción automática que cancela
    los turnos puede no haber corrido todavía.
    """
    if not reserva.es_abonado_mensual:
        return False
    if reserva.estado_pago == Reserva.EstadoPago.PAGADO:
        return False
    from apps.turnos.abono_mensual import plazo_pago_vencido

    return plazo_pago_vencido(reserva.grupo_mensual)


def pago_pendiente(reserva: Reserva) -> bool:
    """Abonado elegible pero con el abono aún impago (para avisos en la UI)."""
    return (
        reserva.es_abonado_mensual
        and reserva.estado_pago != Reserva.EstadoPago.PAGADO
    )


def obtener_o_crear_asistencia(reserva: Reserva) -> Asistencia:
    """
    Devuelve (creando si hace falta) la Asistencia de una reserva elegible.
    Si la reserva no es elegible, lanza ValidationError.
    """
    if not _reserva_elegible(reserva):
        raise AsistenciaNoElegible(
            _("El QR se genera para abonos mensuales reservados y para turnos "
              "individuales pagados por completo.")
        )
    if _abono_con_plazo_vencido(reserva):
        raise AsistenciaNoElegible(
            _("El plazo de pago del abono mensual venció (día 10). "
              "Regularizá el pago para acceder al QR.")
        )
    asistencia, _creada = Asistencia.objects.get_or_create(reserva=reserva)
    return asistencia


@transaction.atomic
def marcar_asistencia(codigo, empleado) -> ResultadoMarcado:
    """
    Marca la asistencia identificada por `codigo` (UUID del QR).

    Reglas:
    - La reserva debe estar confirmada y cumplir las condiciones de pago:
      abonos mensuales valen desde la reserva (mientras el plazo del día 10
      no esté vencido); turnos individuales requieren el 100% pagado.
    - Solo se puede marcar dentro de la ventana de asistencia: desde 30 min
      antes del inicio de la clase y hasta que la clase termina.
    - Es idempotente y seguro ante concurrencia: bloquea la fila
      (select_for_update), así dos empleados que escanean a la vez no la
      registran dos veces; el segundo ve "ya registrada".
    """
    try:
        asistencia = (
            Asistencia.objects
            .select_for_update()
            .select_related("reserva", "reserva__turno", "reserva__turno__actividad", "reserva__usuario")
            .get(codigo=codigo)
        )
    except (Asistencia.DoesNotExist, ValidationError, ValueError):
        return ResultadoMarcado(
            exito=False, estado="no_elegible",
            mensaje=str(_("Código de asistencia inválido.")),
        )

    reserva = asistencia.reserva

    if not _reserva_elegible(reserva):
        return ResultadoMarcado(
            exito=False, estado="no_elegible", asistencia=asistencia,
            mensaje=str(_("La reserva no está confirmada o no cumple las condiciones de pago.")),
        )

    if _abono_con_plazo_vencido(reserva):
        return ResultadoMarcado(
            exito=False, estado="no_elegible", asistencia=asistencia,
            mensaje=str(_("El abono mensual no fue pagado en término (venció el día 10). "
                          "No se puede registrar la asistencia.")),
        )

    if asistencia.presente:
        return ResultadoMarcado(
            exito=True, estado="ya_registrada", asistencia=asistencia,
            mensaje=str(_("La asistencia ya había sido registrada.")),
        )

    apertura, cierre = ventana_asistencia(reserva.turno)
    ahora = timezone.now()
    if ahora < apertura:
        return ResultadoMarcado(
            exito=False, estado="fuera_de_ventana", asistencia=asistencia,
            mensaje=str(_(
                "Todavía no se puede registrar la asistencia. Se habilita 30 minutos "
                "antes del inicio de la clase (%(hora)s).") % {"hora": apertura.strftime("%H:%M %d/%m")}),
        )
    if ahora > cierre:
        return ResultadoMarcado(
            exito=False, estado="fuera_de_ventana", asistencia=asistencia,
            mensaje=str(_("El horario para registrar la asistencia de esta clase ya finalizó.")),
        )

    asistencia.presente = True
    asistencia.fecha_registro = ahora
    asistencia.registrado_por = empleado
    asistencia.save(update_fields=["presente", "fecha_registro", "registrado_por"])

    return ResultadoMarcado(
        exito=True, estado="registrada", asistencia=asistencia,
        mensaje=str(_("Asistencia registrada correctamente.")),
    )
