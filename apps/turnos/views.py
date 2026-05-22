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
from datetime import date as date_type, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Count, Q
from apps.accounts.decorators import rol_requerido

from apps.actividades.models import Actividad
from .forms import (
    PasoActividadForm,
    PasoFechaForm,
    PasoHoraForm,
    PasoSeleccionFechasForm,
    PasoTipoAbonoForm,
    TurnoForm,
)
from .models import GrupoReservaMensual, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS, Reserva, Turno
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
        reserva = services.cancelar_reserva(request.user, pk)
        logger.info("Reserva cancelada: %s por usuario %s", pk, request.user.pk)
        messages.success(
            request,
            _("Reserva del %(turno)s cancelada.") % {"turno": reserva.turno},
        )
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("turnos:mis_reservas")


@login_required
@require_POST
def cancelar_grupo_mensual(request, pk):
    try:
        grupo = services.cancelar_grupo_mensual(request.user, pk)
        logger.info("Grupo cancelado: %s por usuario %s", pk, request.user.pk)
        messages.success(request, _("Todas las reservas del grupo fueron canceladas."))
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("turnos:mis_reservas")


class VirtualTurno:
    def __init__(self, actividad, fecha, hora):
        self.pk = None
        self.actividad = actividad
        self.fecha = fecha
        self.hora = hora
        self.cupos = actividad.cupos
        self.confirmadas_count = 0
        self.precio_override = None

    @property
    def cupos_totales(self) -> int:
        return self.cupos

    @property
    def cupos_ocupados(self) -> int:
        return 0

    @property
    def cupos_libres(self) -> int:
        return self.cupos

    @property
    def esta_lleno(self) -> bool:
        return False

    @property
    def lista_espera(self):
        return Reserva.objects.none()

    @property
    def reservas(self):
        class EmptyReservas:
            def all(self):
                return Reserva.objects.none()
            def count(self):
                return 0
        return EmptyReservas()

    @property
    def precio_efectivo(self):
        return self.actividad.precio_turno


@login_required
@rol_requerido("admin")
def panel_turnos(request):
    fecha_str = request.GET.get("fecha")
    try:
        fecha = date_type.fromisoformat(fecha_str) if fecha_str else date_type.today()
    except ValueError:
        fecha = date_type.today()

    actividad_id = request.GET.get("actividad")
    estado_ocupacion = request.GET.get("estado_ocupacion", "todos")

    # Get all activities to build the grid
    actividades = Actividad.objects.all()
    
    # Filter the activities we actually loop over
    actividades_filtradas = actividades
    if actividad_id and actividad_id != "todas":
        try:
            actividades_filtradas = actividades_filtradas.filter(id=int(actividad_id))
        except ValueError:
            pass

    # Query existing database turnos for the given date
    turnos_db = (
        Turno.objects
        .filter(fecha=fecha)
        .select_related("actividad")
        .prefetch_related("reservas__usuario")
        .annotate(
            confirmadas_count=Count(
                "reservas",
                filter=Q(reservas__estado=Reserva.Estado.CONFIRMADA)
            )
        )
    )
    if actividad_id and actividad_id != "todas":
        turnos_db = turnos_db.filter(actividad_id=actividad_id)

    turnos_map = {
        (t.actividad_id, t.hora): t
        for t in turnos_db
    }

    from .models import HORAS_VALIDAS, DIAS_HABILES, FERIADOS_INAMOVIBLES

    es_feriado = (fecha.month, fecha.day) in FERIADOS_INAMOVIBLES
    es_dia_invalido = (fecha.weekday() not in DIAS_HABILES) or es_feriado

    # Build the full list of slots (persisted + virtual)
    slots = []
    if not es_dia_invalido:
        for hora in HORAS_VALIDAS:
            for act in actividades_filtradas:
                turno = turnos_map.get((act.id, hora))
                if not turno:
                    turno = VirtualTurno(act, fecha, hora)
                slots.append(turno)

    # Filter based on occupancy
    filtered_slots = []
    for s in slots:
        if estado_ocupacion == "vacios":
            if s.confirmadas_count == 0:
                filtered_slots.append(s)
        elif estado_ocupacion == "ocupados":
            if s.confirmadas_count > 0:
                filtered_slots.append(s)
        elif estado_ocupacion == "llenos":
            if s.confirmadas_count >= s.cupos_totales:
                filtered_slots.append(s)
        else:  # "todos"
            filtered_slots.append(s)

    return render(request, "turnos/panel_turnos.html", {
        "turnos": filtered_slots,
        "fecha": fecha,
        "actividades": actividades,
        "actividad_seleccionada": actividad_id,
        "estado_seleccionado": estado_ocupacion,
        "es_dia_invalido": es_dia_invalido,
        "es_feriado": es_feriado,
    })


def _guardar_y_propagar_turno(form, turno):
    with transaction.atomic():
        turno = form.save(commit=False)
        turno.full_clean()
        modificar_futuros = form.cleaned_data.get("modificar_futuros", False)
        if modificar_futuros:
            turno.save()
            from .models import DIAS_HABILES, FERIADOS_INAMOVIBLES
            futures_dates = []
            for w in range(1, 105):
                future_date = turno.fecha + timedelta(weeks=w)
                if future_date.weekday() in DIAS_HABILES and (future_date.month, future_date.day) not in FERIADOS_INAMOVIBLES:
                    futures_dates.append(future_date)
            
            existing_turnos = Turno.objects.filter(
                actividad=turno.actividad,
                hora=turno.hora,
                fecha__in=futures_dates
            )
            existing_dates = set()
            for t in existing_turnos:
                t.cupos = max(turno.cupos, t.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count())
                t.precio_override = turno.precio_override
                t.save()
                existing_dates.add(t.fecha)
            
            turnos_to_create = []
            for d in futures_dates:
                if d not in existing_dates:
                    turnos_to_create.append(
                        Turno(
                            actividad=turno.actividad,
                            fecha=d,
                            hora=turno.hora,
                            cupos=turno.cupos,
                            precio_override=turno.precio_override
                        )
                    )
            if turnos_to_create:
                Turno.objects.bulk_create(turnos_to_create)
        else:
            turno.save()
    return turno


@login_required
@rol_requerido("admin")
def editar_turno(request, pk):
    turno = get_object_or_404(Turno, pk=pk)
    if request.method == "POST":
        form = TurnoForm(request.POST, instance=turno)
        if form.is_valid():
            try:
                _guardar_y_propagar_turno(form, turno)
                messages.success(request, _("Turno modificado correctamente."))
                return redirect("panel_turnos")
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = TurnoForm(instance=turno)

    return render(request, "turnos/editar_turno.html", {
        "form": form,
        "turno": turno,
    })


@login_required
@rol_requerido("admin")
def editar_turno_slot(request, actividad_id, fecha_str, hora):
    try:
        fecha = date_type.fromisoformat(fecha_str)
    except ValueError:
        messages.error(request, _("Fecha no válida."))
        return redirect("panel_turnos")

    actividad = get_object_or_404(Actividad, id=actividad_id)
    turno = Turno.objects.filter(actividad=actividad, fecha=fecha, hora=hora).first()
    if turno:
        return redirect("editar_turno", pk=turno.pk)

    turno = Turno(actividad=actividad, fecha=fecha, hora=hora, cupos=actividad.cupos)

    if request.method == "POST":
        form = TurnoForm(request.POST, instance=turno)
        if form.is_valid():
            try:
                _guardar_y_propagar_turno(form, turno)
                messages.success(request, _("Turno creado y modificado correctamente."))
                return redirect("panel_turnos")
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = TurnoForm(instance=turno)

    return render(request, "turnos/editar_turno.html", {
        "form": form,
        "turno": turno,
    })


def _obtener_datos_eliminacion(actividad, fecha, hora, turno_db=None):
    if not turno_db:
        turno_db = Turno.objects.filter(actividad=actividad, fecha=fecha, hora=hora).first()
    
    turno = turno_db if turno_db else VirtualTurno(actividad, fecha, hora)
    reservas_count = turno_db.reservas.count() if turno_db else 0
    
    weekday = fecha.weekday()
    future_turnos_db = Turno.objects.filter(
        actividad=actividad,
        hora=hora,
        fecha__gte=fecha
    )
    future_turnos = [t for t in future_turnos_db if t.fecha.weekday() == weekday]
    reservas_futuras_count = sum(t.reservas.count() for t in future_turnos)
    
    return turno, reservas_count, reservas_futuras_count, future_turnos, turno_db


@login_required
@rol_requerido("admin")
def eliminar_turno(request, pk):
    turno_db = get_object_or_404(Turno, pk=pk)
    turno, reservas_count, reservas_futuras_count, future_turnos, unused_turno_db = _obtener_datos_eliminacion(
        turno_db.actividad, turno_db.fecha, turno_db.hora, turno_db=turno_db
    )

    if request.method == "POST":
        tipo_eliminacion = request.POST.get("tipo_eliminacion", "este_dia")
        if tipo_eliminacion == "todos_futuros":
            deleted_count = len(future_turnos)
            with transaction.atomic():
                for t in future_turnos:
                    t.delete()
            messages.success(
                request,
                _("Se eliminaron %(count)d turnos programados (hoy y futuros) para este día y horario.")
                % {"count": deleted_count}
            )
        else:
            turno_db.delete()
            messages.success(
                request,
                _("El turno del %(fecha)s a las %(hora)02d:00 fue eliminado exitosamente.")
                % {"fecha": turno.fecha, "hora": turno.hora}
            )
        return redirect("panel_turnos")

    return render(request, "turnos/eliminar_turno_confirm.html", {
        "turno": turno,
        "reservas_count": reservas_count,
        "reservas_futuras_count": reservas_futuras_count,
        "es_virtual": False,
    })


@login_required
@rol_requerido("admin")
def eliminar_turno_slot(request, actividad_id, fecha_str, hora):
    try:
        fecha = date_type.fromisoformat(fecha_str)
    except ValueError:
        messages.error(request, _("Fecha no válida."))
        return redirect("panel_turnos")

    actividad = get_object_or_404(Actividad, id=actividad_id)
    turno, reservas_count, reservas_futuras_count, future_turnos, turno_db = _obtener_datos_eliminacion(
        actividad, fecha, hora
    )

    if request.method == "POST":
        tipo_eliminacion = request.POST.get("tipo_eliminacion", "este_dia")
        if tipo_eliminacion == "todos_futuros":
            deleted_count = len(future_turnos)
            with transaction.atomic():
                for t in future_turnos:
                    t.delete()
            messages.success(
                request,
                _("Se eliminaron %(count)d turnos programados (hoy y futuros) para este día y horario.")
                % {"count": deleted_count}
            )
        else:
            if turno_db:
                turno_db.delete()
                messages.success(
                    request,
                    _("El turno del %(fecha)s a las %(hora)02d:00 fue eliminado exitosamente.")
                    % {"fecha": fecha, "hora": hora}
                )
            else:
                messages.success(request, _("El turno ya estaba vacío, no fue necesario eliminar nada."))
        return redirect("panel_turnos")

    return render(request, "turnos/eliminar_turno_confirm.html", {
        "turno": turno,
        "reservas_count": reservas_count,
        "reservas_futuras_count": reservas_futuras_count,
        "es_virtual": (turno_db is None),
    })
