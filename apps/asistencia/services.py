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

    Se muestra mientras la reserva sea elegible (confirmada + pagada por
    completo) y la ventana de asistencia no haya cerrado. Una vez que pasó el
    horario de la clase, el QR ya no sirve y deja de mostrarse.
    """
    return _reserva_elegible(reserva) and not ventana_cerrada(reserva.turno)


def _reserva_elegible(reserva: Reserva) -> bool:
    return (
        reserva.estado == Reserva.Estado.CONFIRMADA
        and reserva.estado_pago == Reserva.EstadoPago.PAGADO
    )


def obtener_o_crear_asistencia(reserva: Reserva) -> Asistencia:
    """
    Devuelve (creando si hace falta) la Asistencia de una reserva pagada por
    completo y confirmada. Si la reserva no es elegible, lanza ValidationError.
    """
    if not _reserva_elegible(reserva):
        raise AsistenciaNoElegible(
            _("El QR se genera solo para clases confirmadas y pagadas por completo.")
        )
    asistencia, _creada = Asistencia.objects.get_or_create(reserva=reserva)
    return asistencia


@transaction.atomic
def marcar_asistencia(codigo, empleado) -> ResultadoMarcado:
    """
    Marca la asistencia identificada por `codigo` (UUID del QR).

    Reglas:
    - La reserva debe estar confirmada y pagada por completo.
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
            mensaje=str(_("La reserva no está confirmada o no está pagada por completo.")),
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
