"""
Notificaciones por correo de la app turnos.

Envía al usuario un comprobante (HTML + texto de respaldo) con el detalle de los
turnos reservados y el estado de pago. Reutiliza la configuración de mail del
proyecto (SMTP real si está el .env, backend de consola en caso contrario).

El tipo de comprobante se deriva del estado de pago de la reserva:
  - PAGADO    -> "Comprobante de pago"
  - SENADO    -> "Comprobante de seña" (incluye saldo pendiente)
  - PENDIENTE -> "Comprobante de reserva" (pago pendiente)

El envío nunca debe romper el flujo de reserva: si el mail falla, se loguea
el error y se devuelve False, pero la reserva ya quedó confirmada igual.
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .models import Reserva

logger = logging.getLogger(__name__)

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Configuración visual por estado de pago: (clave, título, asunto, color del badge)
_CONFIG_ESTADO = {
    Reserva.EstadoPago.PAGADO: {
        "titulo": "Comprobante de pago",
        "asunto": "Comprobante de pago - Club360",
        "badge_label": "Pagado",
        "badge_color": "#16a34a",  # verde de marca
    },
    Reserva.EstadoPago.SENADO: {
        "titulo": "Comprobante de seña",
        "asunto": "Comprobante de seña - Club360",
        "badge_label": "Señado",
        "badge_color": "#d97706",  # ámbar
    },
    Reserva.EstadoPago.PENDIENTE: {
        "titulo": "Comprobante de reserva",
        "asunto": "Comprobante de reserva - Club360",
        "badge_label": "Pago pendiente",
        "badge_color": "#6b7280",  # gris
    },
}


def _detalle_reserva(reserva) -> dict:
    """Arma el diccionario de datos de un turno para el comprobante."""
    turno = reserva.turno
    fecha = turno.fecha
    return {
        "actividad": turno.actividad.get_nombre_display(),
        "fecha": fecha.strftime("%d/%m/%Y"),
        "dia_semana": DIAS_SEMANA[fecha.weekday()],
        "hora": f"{turno.hora:02d}:00",
        "estado": reserva.get_estado_display(),
    }


def _estado_pago_agregado(reservas) -> str:
    """
    Estado de pago representativo de un conjunto de reservas.

    Todas pagadas -> PAGADO; alguna pendiente -> PENDIENTE; en otro caso SENADO.
    """
    estados = {r.estado_pago for r in reservas}
    if estados == {Reserva.EstadoPago.PAGADO}:
        return Reserva.EstadoPago.PAGADO
    if Reserva.EstadoPago.PENDIENTE in estados:
        return Reserva.EstadoPago.PENDIENTE
    return Reserva.EstadoPago.SENADO


def enviar_comprobante_reserva(usuario, reservas, *, referencia: str = "", tipo_pago: str = "", monto_pagado: Decimal | None = None) -> bool:
    """
    Envía un comprobante por mail (HTML + texto) de las reservas indicadas.

    `reservas` puede ser una sola reserva o un iterable de reservas (abono
    mensual). Una registración/pago = un comprobante (los abonos listan todos
    sus turnos en el mismo mail).

    El tipo de comprobante (pago / seña / pendiente) se deriva del estado de
    pago de las reservas, que el caller debe haber actualizado antes de llamar.

    Devuelve True si el correo se envió, False si no había destinatario o si
    el envío falló. Nunca propaga excepciones para no romper el flujo de reserva.
    """
    if reservas is None:
        return False
    if not isinstance(reservas, (list, tuple)):
        reservas = [reservas]
    reservas = [r for r in reservas if r is not None]
    if not reservas:
        return False

    if not getattr(usuario, "email", ""):
        logger.warning("No se envió comprobante: usuario %s sin email.", getattr(usuario, "pk", "?"))
        return False

    estado_pago = _estado_pago_agregado(reservas)
    config = _CONFIG_ESTADO[estado_pago]

    detalles = [_detalle_reserva(r) for r in reservas]
    monto_total = sum((r.monto_total for r in reservas), Decimal("0"))
    monto_abonado = sum(((r.precio_abonado or Decimal("0")) for r in reservas), Decimal("0"))
    monto_saldo = (monto_total - monto_abonado).quantize(Decimal("0.01"))

    contexto = {
        "usuario": usuario,
        "reservas": detalles,
        "cantidad": len(detalles),
        "es_abono": len(detalles) > 1,
        "referencia": referencia,
        "monto_total": monto_total,
        "monto_abonado": monto_abonado,
        "monto_saldo": monto_saldo,
        "monto_pagado": monto_pagado,
        "estado_pago": estado_pago,
        "es_pagado": estado_pago == Reserva.EstadoPago.PAGADO,
        "es_senado": estado_pago == Reserva.EstadoPago.SENADO,
        "es_pendiente": estado_pago == Reserva.EstadoPago.PENDIENTE,
        "titulo": config["titulo"],
        "badge_label": config["badge_label"],
        "badge_color": config["badge_color"],
        "color_marca": "#16a34a",
    }

    cuerpo_texto = render_to_string("turnos/emails/comprobante_turno.txt", contexto)
    cuerpo_html = render_to_string("turnos/emails/comprobante_turno.html", contexto)

    try:
        mail = EmailMultiAlternatives(
            config["asunto"],
            cuerpo_texto,
            settings.DEFAULT_FROM_EMAIL,
            [usuario.email],
        )
        mail.attach_alternative(cuerpo_html, "text/html")
        mail.send()
        logger.info(
            "Comprobante (%s) enviado a %s (%d turno/s, ref %s).",
            estado_pago, usuario.email, len(detalles), referencia or "—",
        )
        return True
    except Exception:
        logger.exception("Error al enviar comprobante de reserva a %s.", usuario.email)
        return False
