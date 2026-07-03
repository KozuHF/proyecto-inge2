import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import rol_requerido
from apps.accounts.repository import UsuarioRepository
from apps.turnos.models import Reserva
from . import services
from .forms import BuscarPorDniForm
from .models import Asistencia
from .qr import svg_qr

logger = logging.getLogger(__name__)


@login_required
def qr_reserva(request, pk):
    """Muestra el QR de asistencia de una reserva propia, pagada por completo."""
    reserva = Reserva.objects.select_related(
        "turno", "turno__actividad", "usuario"
    ).filter(pk=pk).first()
    if reserva is None or reserva.usuario != request.user:
        raise Http404("Reserva no encontrada o no pertenece al usuario.")

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
def marcar_por_dni(request):
    """
    Marcado manual de asistencia para clientes que olvidaron el QR.

    El empleado ingresa el DNI; si el cliente tiene reservas dentro del rango
    horario de la clase, se listan para marcar la asistencia a mano. El marcado
    en sí lo hace la vista `marcar` (reusa toda la validación y el registro).
    """
    form = BuscarPorDniForm(request.POST or None)
    cliente = None
    reservas_info = None
    buscado = False

    if request.method == "POST" and form.is_valid():
        buscado = True
        cliente = UsuarioRepository.obtener_por_documento(form.cleaned_data["nro_documento"])
        if cliente is not None:
            reservas_info = []
            for reserva in services.reservas_marcables_ahora(cliente):
                try:
                    asistencia = services.obtener_o_crear_asistencia(reserva)
                except ValidationError:
                    continue
                reservas_info.append({
                    "reserva": reserva,
                    "asistencia": asistencia,
                    "pago_pendiente": services.pago_pendiente(reserva),
                })

    return render(request, "asistencia/marcar_por_dni.html", {
        "form": form,
        "cliente": cliente,
        "reservas_info": reservas_info,
        "buscado": buscado,
    })


@login_required
@rol_requerido(["admin", "employee"])
@require_http_methods(["GET", "POST"])
def marcar(request, codigo):
    """
    GET  → pantalla de confirmación con datos del cliente y la clase.
    POST → registra la asistencia y muestra el resultado.
    """
    try:
        asistencia = (
            Asistencia.objects
            .select_related("reserva", "reserva__turno", "reserva__turno__actividad", "reserva__usuario")
            .filter(codigo=codigo[:36])
            .first()
        )
    except Exception:
        asistencia = None

    if asistencia is None:
        return render(request, "asistencia/qr_invalido.html")

    if asistencia.reserva.estado == Reserva.Estado.CANCELADA:
        resultado = services.resultado_reserva_cancelada(asistencia)
        return render(request, "asistencia/marcar_resultado.html", {
            "resultado": resultado,
            "asistencia": asistencia,
            "origen": request.GET.get("origen", "qr"),
        })

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
            "origen": request.GET.get("origen", "qr"),
        })

    return render(request, "asistencia/marcar.html", {
        "asistencia": asistencia,
        "codigo": codigo,
        "pago_pendiente": services.pago_pendiente(asistencia.reserva),
        "origen": request.GET.get("origen", "qr"),
    })
