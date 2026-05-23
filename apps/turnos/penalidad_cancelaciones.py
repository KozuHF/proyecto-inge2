"""
Penalización por cancelaciones frecuentes de abono mensual.

Si el usuario cancela 3 o más clases de abono mensual en un mismo mes calendario,
pierde el 20 % de descuento en abonos «solo del 16 en adelante» durante el mes siguiente.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .abono_mensual import DESCUENTO_SEGUNDA_QUINCENA, REGLA_SEGUNDA_QUINCENA

UMBRAL_CANCELACIONES = 3

MESES = [
    _("enero"), _("febrero"), _("marzo"), _("abril"), _("mayo"), _("junio"),
    _("julio"), _("agosto"), _("septiembre"), _("octubre"), _("noviembre"), _("diciembre"),
]


def _mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    if mes == 12:
        return anio + 1, 1
    return anio, mes + 1


def nombre_mes(mes: int) -> str:
    if 1 <= mes <= 12:
        return str(MESES[mes - 1])
    return str(mes)


def contar_cancelaciones_abono_mensual(usuario, anio: int, mes: int) -> int:
    from .models import CancelacionAbonoMensual

    return CancelacionAbonoMensual.objects.filter(
        usuario=usuario,
        anio_cancelacion=anio,
        mes_cancelacion=mes,
    ).count()


def usuario_penalizado_descuento_segunda_quincena(
    usuario, anio_abono: int, mes_abono: int
) -> bool:
    """True si en el mes del abono no aplica el 20 % por cancelaciones del mes anterior."""
    anio_prev, mes_prev = _mes_anterior(anio_abono, mes_abono)
    return contar_cancelaciones_abono_mensual(usuario, anio_prev, mes_prev) >= UMBRAL_CANCELACIONES


def descuento_segunda_quincena_para_usuario(
    usuario, anio: int, mes: int, regla_cobro: str
) -> Decimal:
    if regla_cobro != REGLA_SEGUNDA_QUINCENA:
        return Decimal("0")
    if usuario and usuario_penalizado_descuento_segunda_quincena(usuario, anio, mes):
        return Decimal("0")
    return DESCUENTO_SEGUNDA_QUINCENA


def precio_turno_con_regla(
    precio_base: Decimal,
    regla_cobro: str,
    usuario=None,
    anio: int | None = None,
    mes: int | None = None,
) -> Decimal:
    from .abono_mensual import precio_turno_abono

    if regla_cobro == REGLA_SEGUNDA_QUINCENA and usuario and anio and mes:
        if usuario_penalizado_descuento_segunda_quincena(usuario, anio, mes):
            return precio_base
    return precio_turno_abono(precio_base, regla_cobro)


def registrar_cancelacion_abono_mensual(reserva) -> None:
    """Registra una cancelación de turno de abono mensual (mes = fecha de cancelación)."""
    from .models import CancelacionAbonoMensual, Reserva

    if not reserva.grupo_mensual_id:
        return
    if reserva.tipo_reserva not in (Reserva.TipoReserva.VARIOS, Reserva.TipoReserva.MENSUAL):
        return

    hoy = timezone.now().date()
    CancelacionAbonoMensual.objects.create(
        usuario=reserva.usuario,
        reserva=reserva,
        anio_cancelacion=hoy.year,
        mes_cancelacion=hoy.month,
    )


@dataclass
class AvisoPenalidadDescuento:
    tipo: str  # "activa" | "proxima"
    mensaje: str


def aviso_penalidad_en_cuenta(usuario) -> AvisoPenalidadDescuento | None:
    """
    Aviso para Mi cuenta: penalidad vigente este mes o riesgo por cancelaciones del mes actual.
    """
    hoy = timezone.now().date()
    anio, mes = hoy.year, hoy.month

    if usuario_penalizado_descuento_segunda_quincena(usuario, anio, mes):
        anio_inf, mes_inf = _mes_anterior(anio, mes)
        return AvisoPenalidadDescuento(
            tipo="activa",
            mensaje=_(
                "Debido a las frecuentes cancelaciones de abono mensual que realizaste en "
                "%(mes_inf)s %(anio_inf)s, durante %(mes)s %(anio)s no podés acceder al beneficio "
                "del 20 %% de descuento en abonos mensuales con turnos del 16 en adelante. "
                "El beneficio se restablece el mes siguiente si no volvés a superar el límite de cancelaciones."
            )
            % {
                "mes_inf": nombre_mes(mes_inf),
                "anio_inf": anio_inf,
                "mes": nombre_mes(mes),
                "anio": anio,
            },
        )

    cancelaciones = contar_cancelaciones_abono_mensual(usuario, anio, mes)
    if cancelaciones >= UMBRAL_CANCELACIONES:
        anio_sig, mes_sig = _mes_siguiente(anio, mes)
        return AvisoPenalidadDescuento(
            tipo="proxima",
            mensaje=_(
                "Cancelaste %(n)d o más clases de abono mensual en %(mes)s %(anio)s. "
                "En %(mes_sig)s %(anio_sig)s no vas a poder acceder al beneficio del 20 %% de descuento "
                "en abonos mensuales con turnos del 16 en adelante."
            )
            % {
                "n": UMBRAL_CANCELACIONES,
                "mes": nombre_mes(mes),
                "anio": anio,
                "mes_sig": nombre_mes(mes_sig),
                "anio_sig": anio_sig,
            },
        )

    return None


def mensaje_sin_beneficio_segunda_quincena(usuario, anio: int, mes: int) -> str | None:
    """Texto para el flujo de reserva/pago cuando no aplica el 20 % en abonos del 16 en adelante."""
    if not usuario or not usuario_penalizado_descuento_segunda_quincena(usuario, anio, mes):
        return None
    return _(
        "Usted no puede acceder a este beneficio del 20 %% de descuento en abonos mensuales "
        "del 16 en adelante durante el mes de %(mes)s de %(anio)s."
    ) % {"mes": nombre_mes(mes), "anio": anio}


def mensaje_sin_beneficio_segunda_quincena(usuario, anio: int, mes: int) -> str | None:
    """Texto para el flujo de reserva/pago cuando no aplica el 20 % en abonos del 16 en adelante."""
    if not usuario or not usuario_penalizado_descuento_segunda_quincena(usuario, anio, mes):
        return None
    return _(
        "Usted no puede acceder a este beneficio del 20 %% de descuento en abonos mensuales "
        "del 16 en adelante durante el mes de %(mes)s de %(anio)s."
    ) % {"mes": nombre_mes(mes), "anio": anio}
