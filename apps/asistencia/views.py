import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import rol_requerido
from apps.turnos.models import Reserva
from . import services
from .models import Asistencia
from .qr import svg_qr

logger = logging.getLogger(__name__)


@login_required
def qr_reserva(request, pk):
    """Muestra el QR de asistencia de una reserva propia, pagada por completo."""
    reserva = get_object_or_404(
        Reserva.objects.select_related("turno", "turno__actividad", "usuario"),
        pk=pk,
        usuario=request.user,
    )

    try:
        asistencia = services.obtener_o_crear_asistencia(reserva)
    except ValidationError as exc:
        return render(request, "asistencia/qr_no_disponible.html", {
            "reserva": reserva,
            "mensaje": exc.message if hasattr(exc, "message") else str(exc),
        }, status=400)

    # Si ya pasó el horario de la clase, el QR no se muestra más.
    if services.ventana_cerrada(reserva.turno):
        return render(request, "asistencia/qr_no_disponible.html", {
            "reserva": reserva,
            "mensaje": "El horario de asistencia de esta clase ya finalizó.",
        }, status=410)

    ruta_marcado = reverse("asistencia:marcar", kwargs={"codigo": asistencia.codigo})
    # Si hay una dirección base configurada (ej. la del túnel o el dominio real),
    # el QR la usa siempre; si no, se arma según el host de la request.
    if settings.SITE_BASE_URL:
        url_marcado = settings.SITE_BASE_URL + ruta_marcado
    else:
        url_marcado = request.build_absolute_uri(ruta_marcado)
    svg = mark_safe(svg_qr(url_marcado))

    return render(request, "asistencia/qr_reserva.html", {
        "reserva": reserva,
        "asistencia": asistencia,
        "qr_svg": svg,
        "url_marcado": url_marcado,
        "pago_pendiente": services.pago_pendiente(reserva),
    })


@login_required
@rol_requerido(["admin", "employee"])
def escanear(request):
    """Página con escáner de cámara (html5-qrcode) para el empleado."""
    return render(request, "asistencia/escanear.html")


@login_required
@rol_requerido(["admin", "employee"])
@require_http_methods(["GET", "POST"])
def marcar(request, codigo):
    """
    GET  → pantalla de confirmación con datos del cliente y la clase.
    POST → registra la asistencia y muestra el resultado.
    """
    asistencia = (
        Asistencia.objects
        .select_related("reserva", "reserva__turno", "reserva__turno__actividad", "reserva__usuario")
        .filter(codigo=codigo)
        .first()
    )

    if request.method == "POST":
        resultado = services.marcar_asistencia(codigo, request.user)
        if resultado.exito:
            logger.info(
                "Asistencia %s para reserva %s por empleado %s",
                resultado.estado,
                getattr(resultado.asistencia, "reserva_id", "?"),
                request.user.pk,
            )
        return render(request, "asistencia/marcar_resultado.html", {
            "resultado": resultado,
            "asistencia": resultado.asistencia or asistencia,
        })

    return render(request, "asistencia/marcar.html", {
        "asistencia": asistencia,
        "codigo": codigo,
        "pago_pendiente": services.pago_pendiente(asistencia.reserva) if asistencia else False,
    })
