"""
Créditos por deporte: otorgamiento al cancelar con anticipación y uso en pagos.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from apps.turnos.abono_mensual import precio_turno_abono
from apps.turnos.models import GrupoReservaMensual, Reserva

from .constants import EMOJI_POR_DEPORTE, HORAS_ANTELACION_CREDITO
from .models import SaldoCredito


@dataclass
class ResumenCredito:
    actividad: Actividad
    cantidad: int
    emoji: str
    color_ring: str


@dataclass
class ContextoPagoCreditos:
    actividad: Actividad
    saldo: int
    valor_credito: Decimal
    max_creditos: int
    regla_cobro: str | None = None


def emoji_actividad(actividad: Actividad) -> str:
    return EMOJI_POR_DEPORTE.get(actividad.nombre, "🏅")


def valor_credito_por_turno(actividad: Actividad, regla_cobro: str | None = None) -> Decimal:
    """Valor de un crédito al pagar (incluye 20 % si el abono es solo del 16 en adelante)."""
    if regla_cobro:
        return precio_turno_abono(actividad.precio_turno, regla_cobro)
    return actividad.precio_turno


def _inicio_turno(reserva: Reserva) -> datetime:
    turno = reserva.turno
    naive = datetime.combine(turno.fecha, time(hour=turno.hora, minute=0))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def puede_otorgar_credito_cancelacion(reserva: Reserva) -> bool:
    if not reserva.esta_pagada:
        return False
    if reserva.estado == Reserva.Estado.CANCELADA:
        return False
    limite = _inicio_turno(reserva) - timedelta(hours=HORAS_ANTELACION_CREDITO)
    return timezone.now() < limite


def obtener_saldo(usuario, actividad: Actividad) -> int:
    saldo, _ = SaldoCredito.objects.get_or_create(
        usuario=usuario,
        actividad=actividad,
        defaults={"cantidad": 0},
    )
    return saldo.cantidad


def resumen_creditos_usuario(usuario) -> list[ResumenCredito]:
    from .constants import COLOR_RING_POR_DEPORTE

    actividades = Actividad.objects.all()
    saldos = {
        s.actividad_id: s.cantidad
        for s in SaldoCredito.objects.filter(
            usuario=usuario, actividad__in=actividades
        )
    }
    resultado = []
    for actividad in actividades:
        resultado.append(
            ResumenCredito(
                actividad=actividad,
                cantidad=saldos.get(actividad.pk, 0),
                emoji=emoji_actividad(actividad),
                color_ring=COLOR_RING_POR_DEPORTE.get(
                    actividad.nombre, "bg-gray-100"
                ),
            )
        )
    return resultado


@transaction.atomic
def otorgar_credito_cancelacion(reserva: Reserva) -> None:
    saldo, _ = SaldoCredito.objects.select_for_update().get_or_create(
        usuario=reserva.usuario,
        actividad=reserva.turno.actividad,
        defaults={"cantidad": 0},
    )
    saldo.cantidad += 1
    saldo.save(update_fields=["cantidad"])


@transaction.atomic
def otorgar_creditos_por_cancelacion_grupo(reservas: list[Reserva]) -> int:
    """
    Otorga un crédito por cada reserva de la lista (ya validadas antes de cancelar).
    """
    for reserva in reservas:
        otorgar_credito_cancelacion(reserva)
    return len(reservas)


@transaction.atomic
def consumir_creditos(usuario, actividad: Actividad, cantidad: int) -> None:
    if cantidad <= 0:
        return
    try:
        saldo = SaldoCredito.objects.select_for_update().get(
            usuario=usuario, actividad=actividad
        )
    except SaldoCredito.DoesNotExist:
        raise ValidationError(_("No tenés créditos para este deporte."))

    if saldo.cantidad < cantidad:
        raise ValidationError(
            _("No tenés suficientes créditos de %(deporte)s.")
            % {"deporte": actividad.get_nombre_display()}
        )

    saldo.cantidad -= cantidad
    saldo.save(update_fields=["cantidad"])


def calcular_descuento_creditos(
    creditos_usados: int,
    valor_credito: Decimal,
    monto_cobro: Decimal,
) -> Decimal:
    if creditos_usados <= 0:
        return Decimal("0")
    descuento = (valor_credito * creditos_usados).quantize(Decimal("0.01"))
    return min(descuento, monto_cobro)


def validar_creditos_pago(
    usuario,
    actividad: Actividad,
    creditos_usados: int,
    max_creditos: int,
    monto_cobro: Decimal,
    regla_cobro: str | None = None,
) -> tuple[Decimal, Decimal, int]:
    """
    Valida el uso de créditos y devuelve (monto_tarjeta, descuento, creditos_efectivos).
    """
    if creditos_usados < 0:
        raise ValidationError(_("La cantidad de créditos no puede ser negativa."))

    if creditos_usados == 0:
        return monto_cobro, Decimal("0"), 0

    saldo = obtener_saldo(usuario, actividad)
    if creditos_usados > saldo:
        raise ValidationError(
            _("Solo tenés %(n)d crédito(s) de %(deporte)s.")
            % {"n": saldo, "deporte": actividad.get_nombre_display()}
        )

    if creditos_usados > max_creditos:
        raise ValidationError(
            _("Podés usar como máximo %(n)d crédito(s) en este pago.")
            % {"n": max_creditos}
        )

    valor = valor_credito_por_turno(actividad, regla_cobro)
    descuento = calcular_descuento_creditos(creditos_usados, valor, monto_cobro)
    monto_tarjeta = (monto_cobro - descuento).quantize(Decimal("0.01"))

    if descuento <= 0 and creditos_usados > 0:
        raise ValidationError(_("Los créditos no aplican a este monto de pago."))

    return monto_tarjeta, descuento, creditos_usados


def contexto_desde_checkout(usuario, datos) -> ContextoPagoCreditos:
    from apps.turnos.models import MODO_VARIOS_TURNOS

    max_c = datos.cantidad_turnos if datos.modo == MODO_VARIOS_TURNOS else 1
    saldo = obtener_saldo(usuario, datos.actividad)
    return ContextoPagoCreditos(
        actividad=datos.actividad,
        saldo=saldo,
        valor_credito=valor_credito_por_turno(datos.actividad, datos.regla_cobro),
        max_creditos=min(max_c, saldo),
        regla_cobro=datos.regla_cobro,
    )


def contexto_desde_reserva(usuario, reserva: Reserva) -> ContextoPagoCreditos:
    regla = reserva.grupo_mensual.regla_cobro if reserva.grupo_mensual_id else None
    saldo = obtener_saldo(usuario, reserva.turno.actividad)
    return ContextoPagoCreditos(
        actividad=reserva.turno.actividad,
        saldo=saldo,
        valor_credito=valor_credito_por_turno(reserva.turno.actividad, regla),
        max_creditos=min(1, saldo),
        regla_cobro=regla,
    )


def contexto_desde_grupo(usuario, grupo: GrupoReservaMensual) -> ContextoPagoCreditos:
    n = grupo.cantidad_turnos_activos
    saldo = obtener_saldo(usuario, grupo.actividad)
    return ContextoPagoCreditos(
        actividad=grupo.actividad,
        saldo=saldo,
        valor_credito=valor_credito_por_turno(grupo.actividad, grupo.regla_cobro),
        max_creditos=min(n, saldo),
        regla_cobro=grupo.regla_cobro,
    )
