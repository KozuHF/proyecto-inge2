"""
Reglas de negocio para abonos mensuales.

- Si algún turno cae entre el 1 y el 15: pago total obligatorio antes del día 11 del mes;
  si no se cumple, se cancelan los turnos y se suspende al usuario.
- Si todos los turnos son del 16 en adelante: 20 % de descuento y solo pago total (sin seña).
"""
from datetime import date
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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


def monto_total_desde_fechas(actividad, fechas: list[date]) -> tuple[Decimal, str, Decimal]:
    """Devuelve (monto_total, regla_cobro, descuento_porcentaje)."""
    regla = clasificar_regla_abono(fechas)
    unitario = precio_turno_abono(actividad.precio_turno, regla)
    total = (unitario * len(fechas)).quantize(Decimal("0.01"))
    descuento = DESCUENTO_SEGUNDA_QUINCENA if regla == REGLA_SEGUNDA_QUINCENA else Decimal("0")
    return total, regla, descuento


def permite_pago_sena(regla_cobro: str) -> bool:
    return regla_cobro == REGLA_PRIMERA_QUINCENA


def fecha_limite_pago_primera_quincena(anio: int, mes: int) -> date:
    """Último día inclusive para estar al día (día 10); el 11 vence el plazo."""
    return date(anio, mes, DIA_LIMITE_PAGO_PRIMERA_QUINCENA - 1)


def requiere_pago_antes_dia_11(regla_cobro: str) -> bool:
    return regla_cobro == REGLA_PRIMERA_QUINCENA


def plazo_pago_vencido(grupo) -> bool:
    """True si hoy es día 11 o posterior del mes del abono y no está pagado."""
    if not requiere_pago_antes_dia_11(grupo.regla_cobro):
        return False
    if grupo.esta_pagado_grupo:
        return False
    hoy = timezone.now().date()
    if hoy.year != grupo.anio or hoy.month != grupo.mes:
        return False
    return hoy.day >= DIA_LIMITE_PAGO_PRIMERA_QUINCENA


def descripcion_regla(regla_cobro: str) -> str:
    if regla_cobro == REGLA_SEGUNDA_QUINCENA:
        return str(_("Abono del 16 en adelante: 20 % de descuento. Solo pago total."))
    return str(
        _("Abono con turnos del 1 al 15: debe estar pagado en su totalidad antes del día %(dia)s.")
        % {"dia": DIA_LIMITE_PAGO_PRIMERA_QUINCENA}
    )
