"""
Créditos por deporte: otorgamiento al cancelar con anticipación y uso en pagos.
Cada crédito vence 30 días después de ser otorgado.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Min
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from apps.turnos.abono_mensual import precio_turno_abono
from apps.turnos.models import GrupoReservaMensual, Reserva

from .constants import DIAS_VALIDEZ_CREDITO, EMOJI_POR_DEPORTE, HORAS_ANTELACION_CREDITO
from .models import Credito


@dataclass
class ResumenCredito:
    actividad: Actividad
    cantidad: int
    emoji: str
    color_ring: str
    vence_mas_proximo: datetime | None = None


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


def _eliminar_vencidos_sin_usar(usuario=None, actividad: Actividad | None = None) -> int:
    """Elimina créditos no usados que ya pasaron su fecha de vencimiento."""
    qs = Credito.objects.filter(
        consumido_en__isnull=True,
        fecha_vencimiento__lte=timezone.now(),
    )
    if usuario is not None:
        qs = qs.filter(usuario=usuario)
    if actividad is not None:
        qs = qs.filter(actividad=actividad)
    deleted, _ = qs.delete()
    return deleted


def creditos_disponibles_qs(usuario, actividad: Actividad):
    _eliminar_vencidos_sin_usar(usuario, actividad)
    return Credito.objects.filter(
        usuario=usuario,
        actividad=actividad,
        consumido_en__isnull=True,
        fecha_vencimiento__gt=timezone.now(),
    ).order_by("fecha_vencimiento", "fecha_otorgamiento")


def obtener_saldo(usuario, actividad: Actividad) -> int:
    return creditos_disponibles_qs(usuario, actividad).count()


def resumen_creditos_usuario(usuario) -> list[ResumenCredito]:
    from .constants import COLOR_RING_POR_DEPORTE

    _eliminar_vencidos_sin_usar(usuario)
    actividades = Actividad.objects.all()
    resultado = []

    for actividad in actividades:
        disponibles = creditos_disponibles_qs(usuario, actividad)
        cantidad = disponibles.count()
        vence_mas_proximo = None
        if cantidad:
            agg = disponibles.aggregate(min_vence=Min("fecha_vencimiento"))
            vence_mas_proximo = agg["min_vence"]

        resultado.append(
            ResumenCredito(
                actividad=actividad,
                cantidad=cantidad,
                emoji=emoji_actividad(actividad),
                color_ring=COLOR_RING_POR_DEPORTE.get(
                    actividad.nombre, "bg-gray-100"
                ),
                vence_mas_proximo=vence_mas_proximo,
            )
        )
    return resultado


@transaction.atomic
def otorgar_credito_cancelacion(reserva: Reserva) -> Credito:
    ahora = timezone.now()
    return Credito.objects.create(
        usuario=reserva.usuario,
        actividad=reserva.turno.actividad,
        fecha_vencimiento=Credito.calcular_vencimiento(ahora),
        reserva_origen=reserva,
    )


@transaction.atomic
def otorgar_creditos_por_cancelacion_grupo(reservas: list[Reserva]) -> int:
    for reserva in reservas:
        otorgar_credito_cancelacion(reserva)
    return len(reservas)


@transaction.atomic
def consumir_creditos(usuario, actividad: Actividad, cantidad: int) -> None:
    if cantidad <= 0:
        return

    disponibles = list(
        creditos_disponibles_qs(usuario, actividad).select_for_update()[:cantidad]
    )
    if len(disponibles) < cantidad:
        saldo = len(disponibles)
        raise ValidationError(
            _("No tenés suficientes créditos vigentes de %(deporte)s (disponibles: %(n)d).")
            % {"deporte": actividad.get_nombre_display(), "n": saldo}
        )

    ahora = timezone.now()
    for credito in disponibles:
        credito.consumido_en = ahora
        credito.save(update_fields=["consumido_en"])


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
    if creditos_usados < 0:
        raise ValidationError(_("La cantidad de créditos no puede ser negativa."))

    if creditos_usados == 0:
        return monto_cobro, Decimal("0"), 0

    saldo = obtener_saldo(usuario, actividad)
    if creditos_usados > saldo:
        raise ValidationError(
            _("Solo tenés %(n)d crédito(s) vigente(s) de %(deporte)s.")
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
