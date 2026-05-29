"""
Reglas de negocio para abonos mensuales.

- Si algún turno cae entre el 1 y el 15: pago total obligatorio antes del día 11 del mes;
  si no se cumple, se cancelan los turnos y se suspende al usuario.
- Si algún turno cae entre el 1 y el 10: se puede «pagar más tarde» hasta el día 10 a las 23:59.
- Si todos los turnos son del 16 en adelante: 20 % de descuento y solo pago total (sin seña).
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

DIA_LIMITE_PAGO_PRIMERA_QUINCENA = 11
DESCUENTO_SEGUNDA_QUINCENA = Decimal("0.20")

REGLA_PRIMERA_QUINCENA = "primera_quincena"
REGLA_SEGUNDA_QUINCENA = "segunda_quincena"


def clasificar_regla_abono(fechas: list[date]) -> str:
    """
    Clasifica el abono según los días elegidos.
    Si hay al menos un día del 1 al 15 → regla primera quincena (prioritaria).
    Si todos los días son >= 16 → segunda quincena con descuento.
    """
    if not fechas:
        raise ValueError("Se requiere al menos una fecha.")

    if all(f.day >= 16 for f in fechas):
        return REGLA_SEGUNDA_QUINCENA

    if any(1 <= f.day <= 15 for f in fechas):
        return REGLA_PRIMERA_QUINCENA

    return REGLA_PRIMERA_QUINCENA


def precio_turno_abono(precio_base: Decimal, regla_cobro: str) -> Decimal:
    if regla_cobro == REGLA_SEGUNDA_QUINCENA:
        factor = Decimal("1") - DESCUENTO_SEGUNDA_QUINCENA
        return (precio_base * factor).quantize(Decimal("0.01"))
    return precio_base


def monto_total_desde_fechas(
    actividad,
    fechas: list[date],
    usuario=None,
    anio: int | None = None,
    mes: int | None = None,
) -> tuple[Decimal, str, Decimal]:
    """Devuelve (monto_total, regla_cobro, descuento_porcentaje)."""
    from .models import Turno
    from .penalidad_cancelaciones import (
        descuento_segunda_quincena_para_usuario,
        precio_turno_con_regla,
    )

    regla = clasificar_regla_abono(fechas)
    anio = anio or fechas[0].year
    mes = mes or fechas[0].month
    descuento = descuento_segunda_quincena_para_usuario(usuario, anio, mes, regla)

    turnos_existentes = {
        t.fecha: t
        for t in Turno.objects.filter(actividad=actividad, fecha__in=fechas)
    }

    total = Decimal("0")
    for f in fechas:
        turno = turnos_existentes.get(f)
        precio_base = turno.precio_efectivo if turno else actividad.precio_turno
        precio_con_abono = precio_turno_con_regla(precio_base, regla, usuario, anio, mes)
        total += precio_con_abono

    return total.quantize(Decimal("0.01")), regla, descuento


def abono_incluye_turnos_dia_1_a_10(fechas: list[date]) -> bool:
    """True si el abono tiene al menos una clase entre el día 1 y el 10 del mes."""
    return any(1 <= f.day <= 10 for f in fechas)


def permite_pagar_mas_tarde(fechas: list[date]) -> bool:
    return abono_incluye_turnos_dia_1_a_10(fechas)


def permite_pago_sena(regla_cobro: str) -> bool:
    """Los abonos mensuales no admiten seña; solo turnos individuales."""
    return False


def plazo_pago_limite(anio: int, mes: int) -> datetime:
    """Último instante para pagar: día 10 del mes a las 23:59:59 (hora local)."""
    ultimo_dia = date(anio, mes, DIA_LIMITE_PAGO_PRIMERA_QUINCENA - 1)
    naive = datetime.combine(ultimo_dia, time(23, 59, 59))
    return timezone.make_aware(naive, timezone.get_current_timezone())


def texto_tiempo_restante_pago(anio: int, mes: int) -> str | None:
    """Texto para avisos en Mis reservas; None si el plazo ya venció."""
    limite = plazo_pago_limite(anio, mes)
    ahora = timezone.now()
    if ahora >= limite:
        return str(_("El plazo de pago venció. Debías abonar antes del día 11 del mes."))

    delta = limite - ahora
    dias = delta.days
    horas = (delta.seconds // 3600) % 24
    minutos = (delta.seconds // 60) % 60

    if dias > 0:
        parte_dias = ngettext(
            "%(count)d día",
            "%(count)d días",
            dias,
        ) % {"count": dias}
        return str(
            _("Tenés %(parte)s y %(horas)d h para pagar (hasta el día 10 a las 23:59).")
        ) % {"parte": parte_dias, "horas": horas}

    if horas > 0:
        return str(
            _("Tenés %(horas)d h y %(minutos)d min para pagar (hasta el día 10 a las 23:59).")
        ) % {"horas": horas, "minutos": minutos}

    return str(
        _("Tenés %(minutos)d min para pagar (hasta el día 10 a las 23:59).")
    ) % {"minutos": max(minutos, 1)}


def fecha_limite_pago_primera_quincena(anio: int, mes: int) -> date:
    """Último día inclusive para estar al día (día 10); el 11 vence el plazo."""
    return date(anio, mes, DIA_LIMITE_PAGO_PRIMERA_QUINCENA - 1)


def requiere_pago_antes_dia_11(regla_cobro: str) -> bool:
    return regla_cobro == REGLA_PRIMERA_QUINCENA


def plazo_pago_vencido(grupo) -> bool:
    """True si pasó el día 10 a las 23:59 del mes del abono y el grupo sigue impago."""
    if grupo.esta_pagado_grupo:
        return False
    if not grupo.incluye_turnos_dia_1_a_10:
        return False
    return timezone.now() >= plazo_pago_limite(grupo.anio, grupo.mes)


def descripcion_regla(regla_cobro: str, *, con_descuento: bool = True) -> str:
    if regla_cobro == REGLA_SEGUNDA_QUINCENA:
        if con_descuento:
            return str(_("Abono del 16 en adelante: 20 % de descuento. Solo pago total."))
        return str(
            _("Abono del 16 en adelante: sin descuento por cancelaciones del mes anterior. Solo pago total.")
        )
    return str(
        _("Abono con turnos del 1 al 15: debe estar pagado en su totalidad antes del día %(dia)s.")
        % {"dia": DIA_LIMITE_PAGO_PRIMERA_QUINCENA}
    )
