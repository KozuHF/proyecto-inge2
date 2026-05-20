"""
Vistas de la app turnos.

Flujo de reserva en 4 pasos (wizard manual con sesión):
  Paso 1 → /turnos/reservar/               (elegir actividad)
  Paso 2 → /turnos/reservar/fecha/         (elegir fecha)
  Paso 3 → /turnos/reservar/hora/          (elegir hora)
  Paso 4 → /turnos/reservar/confirmar/     (elegir tipo y confirmar)

El estado entre pasos se guarda en request.session bajo la clave "wizard_reserva".
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.actividades.models import Actividad
from .forms import (
    PasoActividadForm,
    PasoFechaForm,
    PasoHoraForm,
    PasoTipoReservaForm,
)
from .models import GrupoReservaMensual, Reserva
from . import services

logger = logging.getLogger(__name__)

_WIZARD_KEY = "wizard_reserva"


# ── Helpers de sesión ─────────────────────────────────────────────────────────

def _wizard_get(request) -> dict:
    return request.session.get(_WIZARD_KEY, {})


def _wizard_set(request, data: dict):
    request.session[_WIZARD_KEY] = data
    request.session.modified = True


def _wizard_clear(request):
    request.session.pop(_WIZARD_KEY, None)


# ── Paso 1: Actividad ─────────────────────────────────────────────────────────

@login_required
def paso_actividad(request):
    """Paso 1 – Elegir actividad."""
    _wizard_clear(request)

    form = PasoActividadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        actividad = form.cleaned_data["actividad"]
        _wizard_set(request, {"actividad_id": actividad.pk})
        return redirect("turnos:paso_fecha")

    return render(request, "turnos/paso_actividad.html", {
        "form": form,
        "paso": 1,
    })


# ── Paso 2: Fecha ─────────────────────────────────────────────────────────────

@login_required
def paso_fecha(request):
    """Paso 2 – Elegir fecha."""
    wizard = _wizard_get(request)
    if "actividad_id" not in wizard:
        return redirect("turnos:paso_actividad")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    form = PasoFechaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        fecha = form.cleaned_data["fecha"]
        wizard["fecha"] = fecha.isoformat()
        _wizard_set(request, wizard)
        return redirect("turnos:paso_hora")

    return render(request, "turnos/paso_fecha.html", {
        "form": form,
        "actividad": actividad,
        "paso": 2,
    })


# ── Paso 3: Hora ──────────────────────────────────────────────────────────────

@login_required
def paso_hora(request):
    """Paso 3 – Elegir hora."""
    from datetime import date as date_type
    wizard = _wizard_get(request)
    if "fecha" not in wizard:
        return redirect("turnos:paso_fecha")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha     = date_type.fromisoformat(wizard["fecha"])

    horas_info = services.obtener_horas_disponibles(actividad, fecha)
    form = PasoHoraForm(request.POST or None, horas_info=horas_info)

    if request.method == "POST" and form.is_valid():
        wizard["hora"] = form.cleaned_data["hora"]
        _wizard_set(request, wizard)
        return redirect("turnos:paso_confirmar")

    return render(request, "turnos/paso_hora.html", {
        "form": form,
        "actividad": actividad,
        "fecha": fecha,
        "paso": 3,
    })


# ── Paso 4: Confirmar ─────────────────────────────────────────────────────────

@login_required
def paso_confirmar(request):
    """Paso 4 – Elegir tipo de reserva y confirmar."""
    from datetime import date as date_type
    wizard = _wizard_get(request)
    if "hora" not in wizard:
        return redirect("turnos:paso_hora")

    actividad          = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha              = date_type.fromisoformat(wizard["fecha"])
    hora               = wizard["hora"]
    mensual_disponible = services.usuario_puede_reservar_mensual()

    form = PasoTipoReservaForm(
        request.POST or None,
        mensual_disponible=mensual_disponible,
    )

    if request.method == "POST" and form.is_valid():
        tipo = form.cleaned_data["tipo"]
        try:
            if tipo == PasoTipoReservaForm.TIPO_MENSUAL:
                grupo = services.reservar_turno_mensual(request.user, actividad, fecha, hora)
                _wizard_clear(request)
                logger.info(
                    "Reserva mensual creada: grupo=%s usuario=%s",
                    grupo.pk, request.user.pk,
                )
                messages.success(
                    request,
                    _("Reserva mensual creada: %d turnos reservados.") % grupo.reservas.count()
                )
                return redirect("turnos:mis_reservas")
            else:
                reserva = services.reservar_turno_individual(request.user, actividad, fecha, hora)
                _wizard_clear(request)
                logger.info(
                    "Reserva individual creada: reserva=%s usuario=%s turno=%s",
                    reserva.pk, request.user.pk, reserva.turno,
                )
                if reserva.estado == Reserva.Estado.EN_ESPERA:
                    messages.warning(
                        request,
                        _("El turno está lleno. Quedaste en lista de espera.")
                    )
                else:
                    messages.success(request, _("Reserva confirmada."))
                return redirect("turnos:mis_reservas")

        except ValidationError as exc:
            messages.error(request, exc.message)

    return render(request, "turnos/paso_confirmar.html", {
        "form": form,
        "actividad": actividad,
        "fecha": fecha,
        "hora": hora,
        "mensual_disponible": mensual_disponible,
        "paso": 4,
    })


# ── Mis reservas ──────────────────────────────────────────────────────────────

@login_required
def mis_reservas(request):
    """Lista de reservas activas e historial del usuario autenticado."""
    reservas_activas = (
        Reserva.objects
        .filter(usuario=request.user, estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA])
        .select_related("turno", "turno__actividad", "grupo_mensual")
        .order_by("turno__fecha", "turno__hora")
    )
    reservas_canceladas = (
        Reserva.objects
        .filter(usuario=request.user, estado=Reserva.Estado.CANCELADA)
        .select_related("turno", "turno__actividad")
        .order_by("-fecha_cancelacion")[:20]
    )
    grupos_mensuales = (
        GrupoReservaMensual.objects
        .filter(usuario=request.user)
        .prefetch_related("reservas")
        .order_by("-fecha_creacion")
    )

    return render(request, "turnos/mis_reservas.html", {
        "reservas_activas":    reservas_activas,
        "reservas_canceladas": reservas_canceladas,
        "grupos_mensuales":    grupos_mensuales,
    })


# ── Cancelar reserva individual ───────────────────────────────────────────────

@login_required
@require_POST
def cancelar_reserva(request, pk):
    """Cancela una reserva individual del usuario."""
    try:
        reserva = services.cancelar_reserva(request.user, pk)
        logger.info("Reserva cancelada: %s por usuario %s", pk, request.user.pk)
        messages.success(
            request,
            _("Reserva del %(turno)s cancelada.") % {"turno": reserva.turno}
        )
    except ValidationError as exc:
        messages.error(request, exc.message)

    return redirect("turnos:mis_reservas")


# ── Cancelar grupo mensual ────────────────────────────────────────────────────

@login_required
@require_POST
def cancelar_grupo_mensual(request, pk):
    """Cancela todas las reservas activas de un grupo mensual del usuario."""
    try:
        grupo = services.cancelar_grupo_mensual(request.user, pk)
        logger.info("Grupo mensual cancelado: %s por usuario %s", pk, request.user.pk)
        messages.success(request, _("Todas las reservas del grupo mensual fueron canceladas."))
    except ValidationError as exc:
        messages.error(request, exc.message)

    return redirect("turnos:mis_reservas")


# ── Vista de staff: turnos del día ────────────────────────────────────────────

@login_required
def turnos_del_dia(request):
    """Vista staff: lista de turnos del día con asistentes."""
    from datetime import date as date_type
    from .models import Turno

    if not request.user.is_staff:
        messages.error(request, _("No tenés permiso para acceder a esta sección."))
        return redirect("turnos:mis_reservas")

    fecha_str = request.GET.get("fecha")
    try:
        fecha = date_type.fromisoformat(fecha_str) if fecha_str else date_type.today()
    except ValueError:
        fecha = date_type.today()

    turnos = (
        Turno.objects
        .filter(fecha=fecha)
        .select_related("actividad")
        .prefetch_related("reservas__usuario")
        .order_by("hora", "actividad__nombre")
    )

    return render(request, "turnos/turnos_del_dia.html", {
        "turnos": turnos,
        "fecha":  fecha,
    })