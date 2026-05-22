"""
Vistas de la app turnos.

Wizard con sesión (`wizard_reserva`):
  Paso 1 → tipo de abono (turno único / varios turnos)
  Paso 2 → actividad
  Paso 3 → fecha (referencia de día de semana si es «varios»)
  Paso 4 → hora
  Paso 5 → confirmar (único) o elegir días del mes (varios)
  Paso 6 → pago obligatorio (/pagos/reservar/)
"""
import logging
from datetime import date as date_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.actividades.models import Actividad
from .forms import (
    PasoActividadForm,
    PasoFechaForm,
    PasoHoraForm,
    PasoSeleccionFechasForm,
    PasoTipoAbonoForm,
)
from .models import GrupoReservaMensual, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS, Reserva
from . import services

logger = logging.getLogger(__name__)

_WIZARD_KEY = "wizard_reserva"


def _wizard_get(request) -> dict:
    return request.session.get(_WIZARD_KEY, {})


def _wizard_set(request, data: dict):
    request.session[_WIZARD_KEY] = data
    request.session.modified = True


def _wizard_clear(request):
    request.session.pop(_WIZARD_KEY, None)


def _requiere_modo(wizard: dict):
    if "modo" not in wizard:
        return redirect("turnos:paso_tipo_abono")
    return None


# ── Paso 1: Tipo de abono ─────────────────────────────────────────────────────

@login_required
def paso_tipo_abono(request):
    services.verificar_plazos_abonos_mensuales(request.user)
    if not services.usuario_puede_reservar(request.user):
        messages.error(
            request,
            _("Tu cuenta está suspendida. Contactá al club para más información."),
        )
        return redirect("accounts:editar", pk=request.user.pk)

    _wizard_clear(request)
    form = PasoTipoAbonoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _wizard_set(request, {"modo": form.cleaned_data["modo"]})
        return redirect("turnos:paso_actividad")
    return render(request, "turnos/paso_tipo_abono.html", {
        "form": form,
        "paso": 1,
        "modo": None,
    })


# ── Paso 2: Actividad ─────────────────────────────────────────────────────────

@login_required
def paso_actividad(request):
    wizard = _wizard_get(request)
    redir = _requiere_modo(wizard)
    if redir:
        return redir

    form = PasoActividadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        wizard["actividad_id"] = form.cleaned_data["actividad"].pk
        _wizard_set(request, wizard)
        return redirect("turnos:paso_fecha")

    return render(request, "turnos/paso_actividad.html", {
        "form": form,
        "paso": 2,
        "modo": wizard.get("modo"),
    })


# ── Paso 3: Fecha ─────────────────────────────────────────────────────────────

@login_required
def paso_fecha(request):
    wizard = _wizard_get(request)
    redir = _requiere_modo(wizard)
    if redir:
        return redir
    if "actividad_id" not in wizard:
        return redirect("turnos:paso_actividad")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    es_varios = wizard["modo"] == MODO_VARIOS_TURNOS
    form = PasoFechaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        wizard["fecha"] = form.cleaned_data["fecha"].isoformat()
        _wizard_set(request, wizard)
        return redirect("turnos:paso_hora")

    return render(request, "turnos/paso_fecha.html", {
        "form": form,
        "actividad": actividad,
        "paso": 3,
        "modo": wizard["modo"],
        "es_varios": es_varios,
    })


# ── Paso 4: Hora ──────────────────────────────────────────────────────────────

@login_required
def paso_hora(request):
    wizard = _wizard_get(request)
    redir = _requiere_modo(wizard)
    if redir:
        return redir
    if "fecha" not in wizard:
        return redirect("turnos:paso_fecha")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha = date_type.fromisoformat(wizard["fecha"])
    horas_info = services.obtener_horas_disponibles(actividad, fecha)
    form = PasoHoraForm(request.POST or None, horas_info=horas_info)

    if request.method == "POST" and form.is_valid():
        wizard["hora"] = form.cleaned_data["hora"]
        _wizard_set(request, wizard)
        if wizard["modo"] == MODO_VARIOS_TURNOS:
            return redirect("turnos:paso_seleccion_fechas")
        return redirect("turnos:paso_confirmar")

    return render(request, "turnos/paso_hora.html", {
        "form": form,
        "actividad": actividad,
        "fecha": fecha,
        "paso": 4,
        "modo": wizard["modo"],
    })


# ── Paso 5a: Confirmar (turno único) ──────────────────────────────────────────

@login_required
def paso_confirmar(request):
    wizard = _wizard_get(request)
    if wizard.get("modo") != MODO_TURNO_UNICO:
        return redirect("turnos:paso_tipo_abono")
    if "hora" not in wizard:
        return redirect("turnos:paso_hora")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha = date_type.fromisoformat(wizard["fecha"])
    hora = wizard["hora"]

    if request.method == "POST":
        try:
            services.calcular_monto_reserva_nueva(
                actividad, MODO_TURNO_UNICO, fecha, hora
            )
            return redirect("pagos:pagar_wizard")
        except ValidationError as exc:
            messages.error(request, exc.message)

    return render(request, "turnos/paso_confirmar.html", {
        "actividad": actividad,
        "fecha": fecha,
        "hora": hora,
        "precio": actividad.precio_turno,
        "paso": 5,
        "modo": wizard["modo"],
    })


# ── Paso 5b: Selección de días (varios turnos) ────────────────────────────────

@login_required
def paso_seleccion_fechas(request):
    wizard = _wizard_get(request)
    if wizard.get("modo") != MODO_VARIOS_TURNOS:
        return redirect("turnos:paso_tipo_abono")
    if "hora" not in wizard:
        return redirect("turnos:paso_hora")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha_ref = date_type.fromisoformat(wizard["fecha"])
    hora = wizard["hora"]

    try:
        fechas_candidatas = services.obtener_fechas_candidatas_varios(fecha_ref, hora)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:paso_fecha")

    form = PasoSeleccionFechasForm(
        request.POST or None,
        fechas_candidatas=fechas_candidatas,
    )

    if request.method == "POST" and form.is_valid():
        wizard["fechas_seleccionadas"] = form.cleaned_data["fechas"]
        try:
            services.calcular_monto_reserva_nueva(
                actividad,
                MODO_VARIOS_TURNOS,
                fecha_ref,
                hora,
                fechas_seleccionadas=[
                    date_type.fromisoformat(f) for f in wizard["fechas_seleccionadas"]
                ],
            )
            _wizard_set(request, wizard)
            return redirect("pagos:pagar_wizard")
        except ValidationError as exc:
            messages.error(request, exc.message)

    nombres_dia = [_("Lunes"), _("Martes"), _("Miércoles"), _("Jueves"), _("Viernes"), _("Sábado")]
    dia_nombre = nombres_dia[fecha_ref.weekday()] if fecha_ref.weekday() < 6 else ""
    meses = [
        _("enero"), _("febrero"), _("marzo"), _("abril"), _("mayo"), _("junio"),
        _("julio"), _("agosto"), _("septiembre"), _("octubre"), _("noviembre"), _("diciembre"),
    ]
    mes_nombre = meses[fecha_ref.month - 1]

    return render(request, "turnos/paso_seleccion_fechas.html", {
        "form": form,
        "actividad": actividad,
        "fecha_ref": fecha_ref,
        "hora": hora,
        "dia_nombre": dia_nombre,
        "mes_nombre": mes_nombre,
        "precio_turno": actividad.precio_turno,
        "paso": 5,
        "modo": wizard["modo"],
    })


# ── Mis reservas ──────────────────────────────────────────────────────────────

@login_required
def mis_reservas(request):
    n_sanciones = services.verificar_plazos_abonos_mensuales(request.user)
    if n_sanciones:
        messages.error(
            request,
            _(
                "Un abono mensual no fue pagado antes del día 11. "
                "Se cancelaron los turnos y tu cuenta quedó suspendida."
            ),
        )

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
        .filter(
            usuario=request.user,
            reservas__estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
        )
        .distinct()
        .prefetch_related("reservas__turno__actividad")
        .order_by("-fecha_creacion")
    )

    return render(request, "turnos/mis_reservas.html", {
        "reservas_activas": reservas_activas,
        "reservas_canceladas": reservas_canceladas,
        "grupos_mensuales": grupos_mensuales,
    })


@login_required
@require_POST
def cancelar_reserva(request, pk):
    try:
        reserva, credito_otorgado = services.cancelar_reserva(request.user, pk)
        logger.info("Reserva cancelada: %s por usuario %s", pk, request.user.pk)
        msg = _("Reserva del %(turno)s cancelada.") % {"turno": reserva.turno}
        if credito_otorgado:
            msg += " " + _(
                "Se acreditó 1 crédito de %(deporte)s por cancelar con más de 48 h de anticipación."
            ) % {"deporte": reserva.turno.actividad.get_nombre_display()}
        messages.success(request, msg)
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("turnos:mis_reservas")


@login_required
@require_POST
def cancelar_grupo_mensual(request, pk):
    try:
        grupo, creditos_otorgados = services.cancelar_grupo_mensual(request.user, pk)
        logger.info("Grupo cancelado: %s por usuario %s", pk, request.user.pk)
        msg = _("Todas las reservas del abono mensual fueron canceladas.")
        if creditos_otorgados:
            msg += " " + _(
                "Se acreditaron %(n)d crédito(s) de %(deporte)s por los turnos pagados "
                "cancelados con más de 48 h de anticipación."
            ) % {
                "n": creditos_otorgados,
                "deporte": grupo.actividad.get_nombre_display(),
            }
        messages.success(request, msg)
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("turnos:mis_reservas")


@login_required
def turnos_del_dia(request):
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
        "fecha": fecha,
    })
