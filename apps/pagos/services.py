"""
Gateway de pago simulado para demostración académica.

Tarjetas de demostración (solo uso interno del equipo):
  - 0602 2004 3007 1971 → pago aprobado
  - 1509 2000 0106 1970 → rechazado por fondos insuficientes
"""
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.turnos.models import Reserva

from .models import Pago

FRACCION_SENA = Decimal("0.5")

TIPO_TOTAL = "total"
TIPO_SENA = "sena"
TIPO_SALDO = "saldo"

# Solo para demo — no usar en producción
TARJETAS_DEMO = {
    "0602200430071971": {"tiene_fondos": True},
    "1509200001061970": {"tiene_fondos": False},
}


@dataclass
class ResultadoPago:
    exito: bool
    pago: Pago | None = None
    mensaje: str = ""


def normalizar_numero_tarjeta(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def ultimos_4_digitos(numero: str) -> str:
    pan = normalizar_numero_tarjeta(numero)
    return pan[-4:] if len(pan) >= 4 else pan


def monto_total_reserva(reserva: Reserva) -> Decimal:
    return reserva.monto_total


def monto_seña(total: Decimal) -> Decimal:
    return (total * FRACCION_SENA).quantize(Decimal("0.01"))


def opciones_pago_reserva(reserva: Reserva) -> list[tuple[str, str, Decimal]]:
    """
    Devuelve opciones disponibles: (valor, etiqueta, monto a cobrar).
    """
    total = monto_total_reserva(reserva)

    if reserva.estado_pago == Reserva.EstadoPago.PENDIENTE:
        sena = monto_seña(total)
        return [
            (TIPO_TOTAL, _("Pagar total"), total),
            (TIPO_SENA, _("Pagar seña (50%)"), sena),
        ]

    if reserva.estado_pago == Reserva.EstadoPago.SENADO:
        saldo = reserva.monto_saldo
        return [
            (TIPO_SALDO, _("Completar pago (saldo)"), saldo),
        ]

    return []


def calcular_monto_cobro(reserva: Reserva, tipo_pago: str) -> Decimal:
    opciones = {op[0]: op[2] for op in opciones_pago_reserva(reserva)}
    if tipo_pago not in opciones:
        raise ValidationError(_("Opción de pago no válida para esta reserva."))
    return opciones[tipo_pago]


def obtener_reserva_pagable(usuario, reserva_id: int) -> Reserva:
    try:
        reserva = (
            Reserva.objects
            .select_related("turno", "turno__actividad")
            .get(
                pk=reserva_id,
                usuario=usuario,
                estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
            )
        )
    except Reserva.DoesNotExist:
        raise ValidationError(_("Reserva no encontrada o no disponible para pago."))

    if reserva.estado_pago == Reserva.EstadoPago.PAGADO:
        raise ValidationError(_("Esta reserva ya está pagada."))

    if not opciones_pago_reserva(reserva):
        raise ValidationError(_("No hay opciones de pago disponibles para esta reserva."))

    return reserva


def _aplicar_pago_aprobado(reserva: Reserva, tipo_pago: str, monto_cobrado: Decimal, referencia: str):
    total = monto_total_reserva(reserva)

    if tipo_pago == TIPO_SENA:
        reserva.estado_pago = Reserva.EstadoPago.SENADO
        reserva.precio_abonado = monto_cobrado
    else:
        reserva.estado_pago = Reserva.EstadoPago.PAGADO
        reserva.precio_abonado = total

    reserva.referencia_pago = referencia
    reserva.save(update_fields=["estado_pago", "referencia_pago", "precio_abonado"])


@transaction.atomic
def procesar_pago_reserva(
    usuario,
    reserva_id: int,
    numero_tarjeta: str,
    tipo_pago: str,
) -> ResultadoPago:
    reserva = obtener_reserva_pagable(usuario, reserva_id)
    monto = calcular_monto_cobro(reserva, tipo_pago)
    pan = normalizar_numero_tarjeta(numero_tarjeta)
    ultimos = ultimos_4_digitos(numero_tarjeta)

    def _rechazar(motivo: str, mensaje: str) -> ResultadoPago:
        pago = Pago.objects.create(
            reserva=reserva,
            usuario=usuario,
            monto=monto,
            estado=Pago.Estado.RECHAZADO,
            tipo_cobro=tipo_pago,
            ultimos_4=ultimos or "0000",
            motivo_rechazo=motivo,
        )
        return ResultadoPago(exito=False, pago=pago, mensaje=mensaje)

    if len(pan) != 16:
        return _rechazar(
            _("Número de tarjeta inválido."),
            _("Número de tarjeta inválido. Debe tener 16 dígitos."),
        )

    tarjeta = TARJETAS_DEMO.get(pan)
    if tarjeta is None:
        return _rechazar(
            _("Tarjeta no habilitada en modo demostración."),
            _("Tarjeta no válida para esta demostración."),
        )

    if not tarjeta["tiene_fondos"]:
        return _rechazar(
            _("Fondos insuficientes."),
            _("Pago rechazado: fondos insuficientes."),
        )

    referencia = Pago.generar_referencia()
    pago = Pago.objects.create(
        reserva=reserva,
        usuario=usuario,
        monto=monto,
        estado=Pago.Estado.APROBADO,
        tipo_cobro=tipo_pago,
        referencia=referencia,
        ultimos_4=ultimos,
    )

    _aplicar_pago_aprobado(reserva, tipo_pago, monto, referencia)

    if tipo_pago == TIPO_SENA:
        mensaje = _(
            "Seña abonada correctamente ($%(monto)s). Referencia: %(ref)s"
        ) % {"monto": monto, "ref": referencia}
    elif tipo_pago == TIPO_SALDO:
        mensaje = _(
            "Saldo pagado. Reserva totalmente abonada. Referencia: %(ref)s"
        ) % {"ref": referencia}
    else:
        mensaje = _(
            "Pago total realizado correctamente. Referencia: %(ref)s"
        ) % {"ref": referencia}

    return ResultadoPago(exito=True, pago=pago, mensaje=mensaje)
