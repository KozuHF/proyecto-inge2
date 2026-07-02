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
from django.urls import reverse

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


# ── Invitación de cupo (lista de espera) ──────────────────────────────────────

def _url_absoluta(ruta: str) -> str:
    """Antepone SITE_BASE_URL (túnel/dominio) a una ruta relativa para los mails."""
    base = getattr(settings, "SITE_BASE_URL", "") or ""
    return f"{base}{ruta}" if base else ruta


def _emails_admins() -> list[str]:
    """Emails de los administradores activos."""
    from apps.accounts.models import Roles, Usuario

    return list(
        Usuario.objects
        .filter(rol=Roles.ADMIN, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def enviar_invitacion_cupo(invitacion) -> bool:
    """
    Avisa al candidato que se liberó un cupo y lo invita a aceptarlo. Incluye la
    hora límite para aceptar y el link a la página (donde corre el contador).
    """
    reserva = invitacion.reserva
    usuario = reserva.usuario
    if not getattr(usuario, "email", ""):
        logger.warning("No se envió invitación: usuario %s sin email.", getattr(usuario, "pk", "?"))
        return False

    turno = reserva.turno
    fecha = turno.fecha
    ruta = reverse("turnos:invitacion_detalle", kwargs={"token": invitacion.token})

    contexto = {
        "usuario": usuario,
        "actividad": turno.actividad.get_nombre_display(),
        "fecha": fecha.strftime("%d/%m/%Y"),
        "dia_semana": DIAS_SEMANA[fecha.weekday()],
        "hora": f"{turno.hora:02d}:00",
        "vence": invitacion.fecha_vencimiento,
        "url_invitacion": _url_absoluta(ruta),
        "color_marca": "#16a34a",
    }

    cuerpo_texto = render_to_string("turnos/emails/invitacion_cupo.txt", contexto)
    cuerpo_html = render_to_string("turnos/emails/invitacion_cupo.html", contexto)

    try:
        mail = EmailMultiAlternatives(
            "Se liberó un cupo - Club360",
            cuerpo_texto,
            settings.DEFAULT_FROM_EMAIL,
            [usuario.email],
        )
        mail.attach_alternative(cuerpo_html, "text/html")
        mail.send()
        logger.info("Invitación de cupo enviada a %s (turno %s).", usuario.email, turno)
        return True
    except Exception:
        logger.exception("Error al enviar invitación de cupo a %s.", usuario.email)
        return False


def enviar_aviso_admin_lista_espera(total: int) -> bool:
    """Avisa a los admins que se alcanzó el umbral de clientes en lista de espera."""
    destinatarios = _emails_admins()
    if not destinatarios:
        logger.warning("No hay admins con email para avisar de la lista de espera.")
        return False

    contexto = {"total": total, "color_marca": "#16a34a"}
    cuerpo_texto = render_to_string("turnos/emails/aviso_admin_lista_espera.txt", contexto)
    cuerpo_html = render_to_string("turnos/emails/aviso_admin_lista_espera.html", contexto)

    try:
        mail = EmailMultiAlternatives(
            "Aviso: lista de espera - Club360",
            cuerpo_texto,
            settings.DEFAULT_FROM_EMAIL,
            destinatarios,
        )
        mail.attach_alternative(cuerpo_html, "text/html")
        mail.send()
        logger.info("Aviso de lista de espera (%d) enviado a %d admin(s).", total, len(destinatarios))
        return True
    except Exception:
        logger.exception("Error al enviar aviso de lista de espera a admins.")
        return False


def enviar_aviso_cancelacion_clase(reserva: "Reserva", monto_reembolso: Decimal) -> bool:
    """Notifica al cliente que su clase fue cancelada por el club y se le reembolsará la seña."""
<<<<<<< HEAD
    turno = reserva.turno
    dia_nombre = DIAS_SEMANA[turno.fecha.weekday()]
    contexto = {
        "usuario": reserva.usuario,
        "actividad": turno.actividad.get_nombre_display(),
=======
    return enviar_aviso_cancelacion_clase_por_club(
        reserva,
        "reembolso_sena",
        monto_reembolso=monto_reembolso,
    )


def enviar_aviso_cancelacion_clase_por_club(
    reserva: "Reserva",
    tipo_compensacion: str,
    *,
    monto_reembolso: Decimal | None = None,
) -> bool:
    """
    Aviso de cancelación de una clase puntual por el establecimiento.

    tipo_compensacion: 'credito' | 'reembolso_sena' | 'ninguna'
    """
    usuario = reserva.usuario
    if not getattr(usuario, "email", ""):
        logger.warning(
            "No se envió aviso de cancelación: usuario %s sin email.",
            getattr(usuario, "pk", "?"),
        )
        return False

    turno = reserva.turno
    actividad = turno.actividad.get_nombre_display()
    dia_nombre = DIAS_SEMANA[turno.fecha.weekday()]

    if tipo_compensacion == "credito":
        mensaje_compensacion = (
            f"Se le ha otorgado un crédito de {actividad}."
        )
    elif tipo_compensacion == "reembolso_sena":
        mensaje_compensacion = (
            "Se le ha reintegrado el pago de la seña que había realizado."
        )
    else:
        mensaje_compensacion = ""

    contexto = {
        "usuario": usuario,
        "actividad": actividad,
>>>>>>> Eze
        "fecha": turno.fecha.strftime("%d/%m/%Y"),
        "dia_nombre": dia_nombre,
        "hora": turno.hora,
        "monto_reembolso": monto_reembolso,
<<<<<<< HEAD
    }
    cuerpo_texto = render_to_string("turnos/emails/cancelacion_clase_reembolso.txt", contexto)
    cuerpo_html = render_to_string("turnos/emails/cancelacion_clase_reembolso.html", contexto)
    try:
        mail = EmailMultiAlternatives(
            "Tu clase fue cancelada — Club360",
            cuerpo_texto,
            settings.DEFAULT_FROM_EMAIL,
            [reserva.usuario.email],
        )
        mail.attach_alternative(cuerpo_html, "text/html")
        mail.send()
        logger.info("Aviso de cancelación con reembolso enviado a %s.", reserva.usuario.email)
        return True
    except Exception:
        logger.exception("Error al enviar aviso de cancelación a %s.", reserva.usuario.email)
=======
        "tipo_compensacion": tipo_compensacion,
        "mensaje_compensacion": mensaje_compensacion,
        "color_marca": "#16a34a",
    }
    cuerpo_texto = render_to_string(
        "turnos/emails/cancelacion_clase_por_club.txt", contexto
    )
    cuerpo_html = render_to_string(
        "turnos/emails/cancelacion_clase_por_club.html", contexto
    )

    try:
        mail = EmailMultiAlternatives(
            "Clase cancelada — Club360",
            cuerpo_texto,
            settings.DEFAULT_FROM_EMAIL,
            [usuario.email],
        )
        mail.attach_alternative(cuerpo_html, "text/html")
        mail.send()
        logger.info(
            "Aviso de cancelación de clase (%s) enviado a %s.",
            tipo_compensacion,
            usuario.email,
        )
        return True
    except Exception:
        logger.exception(
            "Error al enviar aviso de cancelación de clase a %s.", usuario.email
        )
>>>>>>> Eze
        return False
