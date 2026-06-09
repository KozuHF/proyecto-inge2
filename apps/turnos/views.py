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

from django.utils import timezone
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
    HorarioDisponibleForm,
)
from .models import GrupoReservaMensual, HorarioDisponible, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS, Reserva, Turno
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
        fecha = form.cleaned_data["fecha"]
        horas_info = services.obtener_horas_disponibles(actividad, fecha)
        if not horas_info:
            form.add_error("fecha", _("No hay horarios disponibles configurados para este día de la semana."))
        else:
            wizard["fecha"] = fecha.isoformat()
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
    form = PasoHoraForm(
        request.POST or None,
        horas_info=horas_info,
        usuario=request.user,
        fecha=fecha,
    )

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
        fechas_candidatas = services.obtener_fechas_candidatas_varios(fecha_ref, hora, actividad=actividad)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:paso_fecha")

    form = PasoSeleccionFechasForm(
        request.POST or None,
        fechas_candidatas=fechas_candidatas,
        usuario=request.user,
        hora=hora,
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
                usuario=request.user,
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

    from .penalidad_cancelaciones import mensaje_sin_beneficio_segunda_quincena

    aviso_sin_beneficio = mensaje_sin_beneficio_segunda_quincena(
        request.user, fecha_ref.year, fecha_ref.month
    )

    return render(request, "turnos/paso_seleccion_fechas.html", {
        "form": form,
        "actividad": actividad,
        "fecha_ref": fecha_ref,
        "hora": hora,
        "dia_nombre": dia_nombre,
        "mes_nombre": mes_nombre,
        "precio_turno": actividad.precio_turno,
        "aviso_sin_beneficio": aviso_sin_beneficio,
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

    from apps.asistencia import services as asistencia_services

    # Solo las próximas (lo accionable). Las clases que ya pasaron van a una
    # página de historial aparte. "Pasó" = la ventana de asistencia cerró.
    reservas_proximas = []
    tiene_historial = False
    for reserva in _reservas_activas_usuario(request.user):
        if asistencia_services.ventana_cerrada(reserva.turno):
            tiene_historial = True
        else:
            reserva.qr_disponible = asistencia_services.qr_disponible(reserva)
            reservas_proximas.append(reserva)

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
        "reservas_activas": reservas_proximas,
        "tiene_historial": tiene_historial,
        "reservas_canceladas": reservas_canceladas,
        "grupos_mensuales": grupos_mensuales,
    })


def _reservas_activas_usuario(usuario):
    """Reservas activas (confirmadas o en espera) del usuario, ordenadas por fecha."""
    return list(
        Reserva.objects
        .filter(usuario=usuario, estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA])
        .select_related("turno", "turno__actividad", "grupo_mensual")
        .order_by("turno__fecha", "turno__hora")
    )


@login_required
def historial_clases(request):
    """Página de historial: clases del usuario que ya pasaron, con su asistencia."""
    from apps.asistencia import services as asistencia_services
    from apps.asistencia.models import Asistencia

    historicas = [
        r for r in _reservas_activas_usuario(request.user)
        if asistencia_services.ventana_cerrada(r.turno)
    ]

    presentes = dict(
        Asistencia.objects
        .filter(reserva__in=historicas)
        .values_list("reserva_id", "presente")
    )
    for reserva in historicas:
        if reserva.estado == Reserva.Estado.CONFIRMADA and reserva.esta_pagada:
            reserva.estado_asistencia = "presente" if presentes.get(reserva.id, False) else "ausente"
        else:
            reserva.estado_asistencia = "no_aplica"

    historicas.reverse()  # más recientes primero

    return render(request, "turnos/historial_clases.html", {
        "reservas_historicas": historicas,
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
    fecha = None
    if fecha_str:
        try:
            fecha = date_type.fromisoformat(fecha_str)
        except ValueError:
            pass

    actividad_id = request.GET.get("actividad")
    estado_ocupacion = request.GET.get("estado_ocupacion", "todos")

    actividades = Actividad.objects.all()

    from .models import DIAS_HABILES, FERIADOS_INAMOVIBLES

    if fecha:
        es_feriado = (fecha.month, fecha.day) in FERIADOS_INAMOVIBLES
        es_dia_invalido = (fecha.weekday() not in DIAS_HABILES) or es_feriado
    else:
        es_feriado = False
        es_dia_invalido = False

    # Solo turnos reales persistidos en BD (no más lejanos que 6 meses desde hoy)
    max_futuro = date_type.today() + timedelta(days=6 * 30)
    turnos_qs = (
        Turno.objects
        .filter(fecha__lte=max_futuro)
        .select_related("actividad")
        .prefetch_related("reservas__usuario")
        .annotate(
            confirmadas_count=Count(
                "reservas",
                filter=Q(reservas__estado=Reserva.Estado.CONFIRMADA)
            )
        )
    )

    if fecha:
        turnos_qs = turnos_qs.filter(fecha=fecha)

        if actividad_id and actividad_id != "todas":
            try:
                turnos_qs = turnos_qs.filter(actividad_id=int(actividad_id))
            except ValueError:
                pass

    # Ordenar por fecha y luego hora
    turnos_qs = turnos_qs.order_by("fecha", "hora", "actividad")

    slots = list(turnos_qs)

    # Adjuntar estado de plantilla (activo/inactivo) a cada turno
    horarios_info = HorarioDisponible.objects.values("actividad_id", "dia_semana", "hora", "activo")
    horarios_map = {
        (h["actividad_id"], h["dia_semana"], h["hora"]): h["activo"]
        for h in horarios_info
    }
    for s in slots:
        key = (s.actividad_id, s.fecha.weekday(), s.hora)
        s.horario_activo = horarios_map.get(key, True)

    # Filtrar por ocupación si se pidió (solo en el backend si se especificó fecha)
    if fecha and estado_ocupacion != "todos":
        filtered = []
        for s in slots:
            if estado_ocupacion == "vacios" and s.confirmadas_count == 0:
                filtered.append(s)
            elif estado_ocupacion == "ocupados" and s.confirmadas_count > 0:
                filtered.append(s)
            elif estado_ocupacion == "llenos" and s.confirmadas_count >= s.cupos:
                filtered.append(s)
        slots = filtered

    return render(request, "turnos/panel_turnos.html", {
        "turnos": slots,
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
    """
    Permite al admin crear o editar un turno puntual para una fecha/hora específica.
    Solo opera sobre turnos reales de BD; no genera turnos virtuales.
    """
    try:
        fecha = date_type.fromisoformat(fecha_str)
    except ValueError:
        messages.error(request, _("Fecha no válida."))
        return redirect("panel_turnos")

    actividad = get_object_or_404(Actividad, id=actividad_id)
    turno = Turno.objects.filter(actividad=actividad, fecha=fecha, hora=hora).first()
    if turno:
        return redirect("editar_turno", pk=turno.pk)

    # Crear turno nuevo; el admin debe tener un HorarioDisponible definido,
    # pero también se permite crear turnos puntuales desde el panel.
    turno = Turno(actividad=actividad, fecha=fecha, hora=hora, cupos=actividad.cupos)

    if request.method == "POST":
        form = TurnoForm(request.POST, instance=turno)
        if form.is_valid():
            try:
                _guardar_y_propagar_turno(form, turno)
                messages.success(request, _("Turno creado correctamente."))
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

    turno = turno_db  # puede ser None si no existe en BD
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
                # Eliminar también la plantilla del horario recurrente
                HorarioDisponible.objects.filter(
                    actividad=turno_db.actividad,
                    dia_semana=turno_db.fecha.weekday(),
                    hora=turno_db.hora
                ).delete()
            messages.success(
                request,
                _("Se eliminaron %(count)d turnos programados (hoy y futuros) y se liberó el horario de origen.")
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

    if turno_db is None and request.method == "GET":
        messages.warning(request, _("No existe ningún turno para esa actividad, fecha y horario."))
        return redirect("panel_turnos")

    if request.method == "POST":
        tipo_eliminacion = request.POST.get("tipo_eliminacion", "este_dia")
        if tipo_eliminacion == "todos_futuros":
            deleted_count = len(future_turnos)
            with transaction.atomic():
                for t in future_turnos:
                    t.delete()
                # Eliminar también la plantilla del horario recurrente
                HorarioDisponible.objects.filter(
                    actividad=actividad,
                    dia_semana=fecha.weekday(),
                    hora=hora
                ).delete()
            messages.success(
                request,
                _("Se eliminaron %(count)d turnos programados (hoy y futuros) y se liberó el horario de origen.")
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


# ── Gestión de HorarioDisponible (solo admin) ─────────────────────────────────

# La vista lista_horarios_disponibles ha sido eliminada. El panel de turnos unifica la gestión.


@login_required
@rol_requerido("admin")
def crear_horario_disponible(request):
    """
    El admin crea un horario recurrente: elige actividad, día de la semana y hora.
    Al guardar, genera automáticamente los Turno de los próximos 6 meses.
    """
    import json
    from collections import defaultdict

    # Determinar qué franjas tienen horarios activos en la base de datos
    horarios_existentes = list(
        HorarioDisponible.objects.filter(activo=True).values("actividad_id", "dia_semana", "hora")
    )
    horarios_existentes_json = json.dumps(horarios_existentes)

    # Determinar qué franjas tienen turnos futuros reales en BD para la ayuda
    hoy = timezone.now().date()
    future_turnos = Turno.objects.filter(fecha__gte=hoy).order_by("fecha")

    turnos_por_slot = defaultdict(list)
    for t in future_turnos:
        wd = t.fecha.weekday()
        slot_key = f"{t.actividad_id}_{wd}_{t.hora}"
        turnos_por_slot[slot_key].append(t.fecha.isoformat())

    turnos_por_slot_json = json.dumps(dict(turnos_por_slot))

    # Mapa de precios predefinidos por actividad (id -> precio)
    precios_por_actividad = {
        str(a.id): str(a.precio_turno)
        for a in Actividad.objects.all()
    }
    precios_por_actividad_json = json.dumps(precios_por_actividad)

    form = HorarioDisponibleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                horario = form.save(commit=False)
                # Precio siempre fijado por el deporte, no editable por el usuario
                horario.precio = horario.actividad.precio_turno
                # Borrar duplicados que no tengan turnos futuros para evitar error de constraint único
                duplicate = HorarioDisponible.objects.filter(
                    actividad=horario.actividad,
                    dia_semana=horario.dia_semana,
                    hora=horario.hora
                )
                if duplicate.exists():
                    duplicate.delete()
                horario.full_clean()
                horario.save()
            creados, omitidos = services.generar_turnos_desde_horario(horario, meses=120)
            messages.success(
                request,
                _(
                    "Horario creado: %(horario)s."
                ) % {"horario": horario, "creados": creados, "omitidos": omitidos},
            )
            return redirect("panel_turnos")
        except ValidationError as e:
            form.add_error(None, e)

    return render(
        request,
        "turnos/crear_horario_disponible.html",
        {
            "form": form,
            "horarios_existentes_json": horarios_existentes_json,
            "turnos_por_slot_json": turnos_por_slot_json,
            "precios_por_actividad_json": precios_por_actividad_json,
        },
    )


@login_required
@rol_requerido("admin")
def editar_horario_disponible(request, pk):
    """
    El admin puede modificar cupos o activar/desactivar un horario existente.
    Si se reactiva un horario inactivo, regenera los turnos faltantes de los próximos 6 meses.
    """
    horario = get_object_or_404(HorarioDisponible, pk=pk)
    estaba_inactivo = not horario.activo
    import json
    from collections import defaultdict

    # Determinar qué franjas tienen horarios activos en la base de datos (excluyendo el actual)
    horarios_existentes = list(
        HorarioDisponible.objects.exclude(pk=pk).filter(activo=True).values("actividad_id", "dia_semana", "hora")
    )
    horarios_existentes_json = json.dumps(horarios_existentes)

    # Determinar qué franjas tienen turnos futuros reales en BD para la ayuda
    hoy = timezone.now().date()
    future_turnos = Turno.objects.filter(fecha__gte=hoy).order_by("fecha")

    turnos_por_slot = defaultdict(list)
    for t in future_turnos:
        wd = t.fecha.weekday()
        slot_key = f"{t.actividad_id}_{wd}_{t.hora}"
        turnos_por_slot[slot_key].append(t.fecha.isoformat())

    turnos_por_slot_json = json.dumps(dict(turnos_por_slot))

    form = HorarioDisponibleForm(request.POST or None, instance=horario)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                h = form.save(commit=False)
                # Borrar duplicados que no tengan turnos futuros para evitar error de constraint único
                duplicate = HorarioDisponible.objects.filter(
                    actividad=h.actividad,
                    dia_semana=h.dia_semana,
                    hora=h.hora
                ).exclude(pk=h.pk)
                if duplicate.exists():
                    duplicate.delete()
                h.full_clean()
                h.save()
            # Si se acaba de reactivar, generar los turnos que faltan
            se_reactivo = estaba_inactivo and h.activo
            if se_reactivo:
                creados, omitidos = services.generar_turnos_desde_horario(h, meses=120)
                messages.success(
                    request,
                    _(
                        "Horario reactivado. "
                        "Se generaron %(creados)d turno(s) "
                        "(%(omitidos)d fecha(s) omitida(s) por ser feriado o ya existir)."
                    ) % {"creados": creados, "omitidos": omitidos},
                )
            else:
                messages.success(request, _("Horario actualizado."))
            return redirect("panel_turnos")
        except ValidationError as e:
            form.add_error(None, e)

    return render(
        request,
        "turnos/editar_horario_disponible.html",
        {
            "form": form,
            "horario": horario,
            "horarios_existentes_json": horarios_existentes_json,
            "turnos_por_slot_json": turnos_por_slot_json,
        },
    )


@login_required
@rol_requerido("admin")
def eliminar_horario_disponible(request, pk):
    """
    Elimina un horario disponible.
    No cancela los turnos/reservas ya existentes; solo deja de generar nuevos.
    """
    horario = get_object_or_404(HorarioDisponible, pk=pk)
    if request.method == "POST":
        str_horario = str(horario)
        horario.delete()
        messages.success(
            request,
            _("Horario eliminado: %(horario)s. Los turnos ya creados no se ven afectados.")
            % {"horario": str_horario},
        )
        return redirect("panel_turnos")

    return render(request, "turnos/eliminar_horario_confirm.html", {"horario": horario})