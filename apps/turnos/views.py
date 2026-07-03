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
    AdminCancelarClaseActividadForm,
    AdminCancelarClaseFechaForm,
    AdminCancelarClaseHoraForm,
    PasoActividadForm,
    PasoDiaSemanaForm,
    PasoFechaForm,
    PasoHoraForm,
    PasoTipoAbonoForm,
    TurnoForm,
    HorarioDisponibleForm,
    EditarPreciosCuposForm,
    EliminarHorarioDiaForm,
    EliminarHorarioFranjaForm,
)
from .models import GrupoReservaMensual, HorarioDisponible, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS, Reserva, Turno
from .abono_mensual import monto_total_desde_fechas
from . import services
from . import cancelacion_clase

logger = logging.getLogger(__name__)

_WIZARD_KEY = "wizard_reserva"
_WIZARD_CANCELAR_CLASE = "wizard_cancelar_clase"


def _wizard_get(request) -> dict:
    return request.session.get(_WIZARD_KEY, {})


def _wizard_set(request, data: dict):
    request.session[_WIZARD_KEY] = data
    request.session.modified = True


def _wizard_clear(request):
    request.session.pop(_WIZARD_KEY, None)


def _wizard_cancelar_get(request) -> dict:
    return request.session.get(_WIZARD_CANCELAR_CLASE, {})


def _wizard_cancelar_set(request, data: dict):
    request.session[_WIZARD_CANCELAR_CLASE] = data
    request.session.modified = True


def _wizard_cancelar_clear(request):
    request.session.pop(_WIZARD_CANCELAR_CLASE, None)


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

    if es_varios:
        form = PasoDiaSemanaForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            dia_semana = form.cleaned_data["dia_semana"]
            anio, mes = (int(x) for x in form.cleaned_data["mes"].split("-"))
            fecha = services.primera_fecha_referencia(dia_semana, anio, mes)
            if fecha is None:
                form.add_error("mes", _("No quedan clases de ese día en el mes elegido."))
            elif not services.horas_configuradas(actividad, dia_semana):
                form.add_error("dia_semana", _("No hay horarios disponibles configurados para ese día de la semana."))
            else:
                wizard["fecha"] = fecha.isoformat()
                _wizard_set(request, wizard)
                return redirect("turnos:paso_hora")
    else:
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
    # En modo abono mensual, la fecha es solo de referencia (define el día de la
    # semana): no bloqueamos la hora por el estado puntual de esa fecha (turno
    # lleno, cancelado, etc.). Las clases ya reservadas o canceladas se informan,
    # clase por clase, en el paso 5.
    es_varios = wizard.get("modo") == MODO_VARIOS_TURNOS
    if es_varios:
        horas_info = services.horas_configuradas(actividad, fecha.weekday())
    else:
        horas_info = services.obtener_horas_disponibles(actividad, fecha)
    form = PasoHoraForm(
        request.POST or None,
        horas_info=horas_info,
        usuario=None if es_varios else request.user,
        fecha=None if es_varios else fecha,
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
        "horas_info": horas_info,
        "es_abono": es_varios,
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

    turno_lleno = services.turno_existente_lleno(actividad, fecha, hora)

    if request.method == "POST":
        if turno_lleno:
            # El turno está completo: se anota en lista de espera sin cobro.
            try:
                services.anotar_en_lista_espera(request.user, actividad, fecha, hora)
                _wizard_clear(request)
                messages.success(
                    request,
                    _(
                        "Te anotamos en la lista de espera, sin cargo. Si se libera un "
                        "cupo te vamos a invitar por mail y ahí podrás pagar la clase."
                    ),
                )
                return redirect("turnos:mis_reservas")
            except ValidationError as exc:
                messages.error(request, exc.message)
        else:
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
        "turno_lleno": turno_lleno,
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
        clases = services.obtener_estado_clases_abono(actividad, fecha_ref, hora, usuario=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:paso_fecha")

    disponibles = [c["fecha"] for c in clases if c["estado"] == "disponible"]

    if request.method == "POST":
        if not disponibles:
            messages.error(request, _("No hay clases disponibles para reservar este mes en ese horario."))
        else:
            try:
                services.calcular_monto_reserva_nueva(
                    actividad, MODO_VARIOS_TURNOS, fecha_ref, hora,
                    fechas_seleccionadas=disponibles, usuario=request.user,
                )
                wizard["fechas_seleccionadas"] = [f.isoformat() for f in disponibles]
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

    monto_total = 0
    if disponibles:
        monto_total, _regla, _desc = monto_total_desde_fechas(
            actividad, disponibles, usuario=request.user, anio=fecha_ref.year, mes=fecha_ref.month
        )

    from .penalidad_cancelaciones import mensaje_sin_beneficio_segunda_quincena

    aviso_sin_beneficio = mensaje_sin_beneficio_segunda_quincena(
        request.user, fecha_ref.year, fecha_ref.month
    )

    return render(request, "turnos/paso_seleccion_fechas.html", {
        "clases": clases,
        "cantidad_disponibles": len(disponibles),
        "monto_total": monto_total,
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


@login_required
@require_POST
def anotar_lista_espera_abono(request):
    """Anota al cliente en la lista de espera de una clase llena, desde el paso 5 del abono."""
    wizard = _wizard_get(request)
    if wizard.get("modo") != MODO_VARIOS_TURNOS or "hora" not in wizard:
        return redirect("turnos:paso_tipo_abono")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    hora = wizard["hora"]
    try:
        fecha = date_type.fromisoformat(request.POST.get("fecha", ""))
    except ValueError:
        messages.error(request, _("Fecha inválida."))
        return redirect("turnos:paso_seleccion_fechas")

    try:
        services.anotar_en_lista_espera(request.user, actividad, fecha, hora)
        messages.success(
            request,
            _("Te anotamos en la lista de espera de esa clase, sin cargo. "
              "Si se libera un cupo te invitamos por mail."),
        )
    except ValidationError as exc:
        messages.error(request, exc.message)
    return redirect("turnos:paso_seleccion_fechas")


@login_required
@require_POST
def anotar_lista_espera_turno_unico(request):
    """Anota al cliente en la lista de espera de una clase llena, directo desde
    el paso 4 (sin pasar por la pantalla de confirmación)."""
    wizard = _wizard_get(request)
    if wizard.get("modo") != MODO_TURNO_UNICO or "fecha" not in wizard:
        return redirect("turnos:paso_tipo_abono")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha = date_type.fromisoformat(wizard["fecha"])
    try:
        hora = int(request.POST.get("hora", ""))
    except (TypeError, ValueError):
        messages.error(request, _("Horario inválido."))
        return redirect("turnos:paso_hora")

    try:
        services.anotar_en_lista_espera(request.user, actividad, fecha, hora)
        _wizard_clear(request)
        messages.success(
            request,
            _(
                "Te anotamos en la lista de espera, sin cargo. Si se libera un "
                "cupo te vamos a invitar por mail y ahí podrás pagar la clase."
            ),
        )
        return redirect("turnos:mis_reservas")
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:paso_hora")


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
    from . import lista_espera
    from .models import InvitacionCupo

    # Lazy-check: vencer invitaciones del usuario cuyo plazo ya pasó antes de listar.
    for inv in InvitacionCupo.objects.filter(
        reserva__usuario=request.user, estado=InvitacionCupo.Estado.PENDIENTE
    ).select_related("reserva", "reserva__turno"):
        lista_espera.procesar_si_vencida(inv)

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
            reservas__estado__in=[
                Reserva.Estado.CONFIRMADA,
                Reserva.Estado.EN_ESPERA,
                Reserva.Estado.INVITADO,
            ],
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
    """Reservas activas (confirmadas, en espera o invitadas) del usuario, por fecha."""
    return list(
        Reserva.objects
        .filter(
            usuario=usuario,
            estado__in=[
                Reserva.Estado.CONFIRMADA,
                Reserva.Estado.EN_ESPERA,
                Reserva.Estado.INVITADO,
            ],
        )
        .select_related("turno", "turno__actividad", "grupo_mensual", "invitacion")
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

    # Sin historial no se muestra la página vacía: se vuelve a Mis reservas.
    if not historicas:
        messages.info(request, _("Todavía no tenés historial de clases."))
        return redirect("turnos:mis_reservas")

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


# ── Invitación de cupo (lista de espera) ──────────────────────────────────────

def _obtener_invitacion(request, token):
    from .models import InvitacionCupo
    return get_object_or_404(
        InvitacionCupo.objects.select_related(
            "reserva", "reserva__turno", "reserva__turno__actividad", "reserva__usuario"
        ),
        token=token,
        reserva__usuario=request.user,
    )


@login_required
def invitacion_detalle(request, token):
    from . import lista_espera

    invitacion = _obtener_invitacion(request, token)
    # Lazy-check: si venció, se procesa antes de mostrar.
    lista_espera.procesar_si_vencida(invitacion)
    invitacion.refresh_from_db()
    return render(request, "turnos/invitacion_detalle.html", {
        "invitacion": invitacion,
        "reserva": invitacion.reserva,
    })


@login_required
@require_POST
def invitacion_aceptar(request, token):
    from . import lista_espera

    invitacion = _obtener_invitacion(request, token)
    try:
        reserva = lista_espera.aceptar(invitacion)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")
    # La reserva queda en INVITADO; se confirma al aprobarse el pago.
    return redirect("pagos:pagar_reserva", reserva.pk)


@login_required
@require_POST
def invitacion_rechazar(request, token):
    from . import lista_espera

    invitacion = _obtener_invitacion(request, token)
    try:
        lista_espera.rechazar(invitacion)
        messages.info(
            request,
            _("Rechazaste la invitación. El cupo se le ofreció al siguiente de la lista."),
        )
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

    # Solo turnos reales persistidos en BD (no más lejanos que 6 meses desde hoy,
    # ni anteriores a hoy: este panel es para gestionar turnos vigentes/futuros).
    hoy_gestion = date_type.today()
    max_futuro = hoy_gestion + timedelta(days=6 * 30)
    turnos_qs = (
        Turno.objects
        .filter(fecha__gte=hoy_gestion, fecha__lte=max_futuro)
        .exclude(cancelado_por_club=True)
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
    horarios_info = HorarioDisponible.objects.values("pk", "actividad_id", "dia_semana", "hora", "activo")
    horarios_map = {
        (h["actividad_id"], h["dia_semana"], h["hora"]): h
        for h in horarios_info
    }
    for s in slots:
        key = (s.actividad_id, s.fecha.weekday(), s.hora)
        h = horarios_map.get(key)
        s.horario_activo = h["activo"] if h else True
        s.horario_pk = h["pk"] if h else None

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


@login_required
@rol_requerido(["admin", "employee"])
def historial_clases_turnos(request):
    """Clases ya dictadas (fecha pasada), de solo lectura. Contraparte de
    'Gestión de Turnos', que desde el fix solo muestra turnos vigentes/futuros."""
    fecha_str = request.GET.get("fecha")
    fecha = None
    if fecha_str:
        try:
            fecha = date_type.fromisoformat(fecha_str)
        except ValueError:
            pass

    actividad_id = request.GET.get("actividad")
    actividades = Actividad.objects.all()

    filtrado = bool(request.GET)
    turnos_qs = Turno.objects.none()

    if filtrado:
        hoy = date_type.today()
        min_pasado = hoy - timedelta(days=6 * 30)

        turnos_qs = (
            Turno.objects
            .filter(fecha__lt=hoy, fecha__gte=min_pasado)
            .select_related("actividad")
            .prefetch_related("reservas__usuario", "reservas__asistencia")
            .annotate(
                confirmadas_count=Count(
                    "reservas", filter=Q(reservas__estado=Reserva.Estado.CONFIRMADA)
                ),
                presentes_count=Count(
                    "reservas", filter=Q(reservas__asistencia__presente=True)
                ),
            )
            .order_by("-fecha", "-hora", "actividad")
        )

        if fecha:
            turnos_qs = turnos_qs.filter(fecha=fecha)

        if actividad_id and actividad_id != "todas":
            try:
                turnos_qs = turnos_qs.filter(actividad_id=int(actividad_id))
            except ValueError:
                pass

    return render(request, "turnos/historial_clases_admin.html", {
        "turnos": turnos_qs,
        "fecha": fecha,
        "actividades": actividades,
        "actividad_seleccionada": actividad_id,
        "filtrado": filtrado,
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
    El admin puede modificar precio, cupos y estado activo de un HorarioDisponible.

    Reglas de precio:
    - Si hay clientes anotados en turnos dentro del próximo mes, el nuevo precio
      se aplica solo a los turnos posteriores a ese límite (los próximos no se tocan).
    - Si no hay clientes en los próximos turnos, se actualiza el precio en todos.

    Reglas de cupos:
    - No se puede bajar por debajo del máximo de anotados en cualquier turno futuro.
    """
    from django.db.models import Count, Max, Q
    from .models import fecha_limite_reserva

    horario = get_object_or_404(HorarioDisponible, pk=pk)
    estaba_inactivo = not horario.activo
    hoy = timezone.now().date()

    # Turnos futuros de este horario (por actividad + día + hora)
    django_week_day = horario.dia_semana + 2  # 0=Lunes → 2, ..., 5=Sábado → 7
    turnos_futuros_qs = Turno.objects.filter(
        actividad=horario.actividad,
        hora=horario.hora,
        fecha__gte=hoy,
        fecha__week_day=django_week_day,
    )

    # Máximo de anotados en cualquier turno futuro (para validación de cupos)
    estados_activos = [Reserva.Estado.CONFIRMADA, Reserva.Estado.INVITADO]
    max_ocupados = (
        turnos_futuros_qs
        .annotate(ocupados=Count("reservas", filter=Q(reservas__estado__in=estados_activos)))
        .aggregate(m=Max("ocupados"))["m"]
    ) or 0

    form = EditarPreciosCuposForm(request.POST or None, instance=horario)
    if request.method == "POST" and form.is_valid():
        nuevo_precio = form.cleaned_data["precio"]
        nuevos_cupos = form.cleaned_data["cupos"]

        # Validar cupos
        if nuevos_cupos < max_ocupados:
            form.add_error(
                "cupos",
                _(
                    "No podés bajar de %(n)d: hay %(n)d persona(s) anotada(s) en la clase más ocupada."
                ) % {"n": max_ocupados},
            )
        else:
            try:
                with transaction.atomic():
                    precio_viejo = horario.precio
                    precio_cambio = nuevo_precio != precio_viejo

                    h = form.save(commit=False)
                    h.save()

                    if precio_cambio:
                        limite = fecha_limite_reserva()
                        tiene_clientes_proximos = turnos_futuros_qs.filter(
                            fecha__lte=limite,
                            reservas__estado__in=estados_activos,
                        ).exists()

                        if tiene_clientes_proximos:
                            # Actualizar solo los turnos más allá del límite
                            turnos_futuros_qs.filter(fecha__gt=limite).update(precio_override=nuevo_precio)
                            messages.warning(
                                request,
                                _(
                                    "Precio actualizado a $%(precio)s. "
                                    "Los turnos con clientes anotados dentro del próximo mes "
                                    "conservan el precio anterior ($%(viejo)s)."
                                ) % {"precio": nuevo_precio, "viejo": precio_viejo},
                            )
                        else:
                            # Sin clientes próximos: actualizar todos
                            turnos_futuros_qs.update(precio_override=nuevo_precio)
                            messages.success(request, _("Precio actualizado a $%(precio)s en todos los turnos futuros.") % {"precio": nuevo_precio})
                    else:
                        messages.success(request, _("Horario actualizado."))

                    # Actualizar cupos en todos los turnos futuros
                    if nuevos_cupos != horario.cupos:
                        turnos_futuros_qs.update(cupos=nuevos_cupos)

                    # Si se reactivó, generar turnos faltantes
                    if estaba_inactivo and h.activo:
                        creados, omitidos = services.generar_turnos_desde_horario(h, meses=120)
                        messages.success(
                            request,
                            _(
                                "Horario reactivado. Se generaron %(creados)d turno(s) "
                                "(%(omitidos)d omitido(s) por feriado o ya existir)."
                            ) % {"creados": creados, "omitidos": omitidos},
                        )

                return redirect("panel_turnos")
            except ValidationError as e:
                form.add_error(None, e)

    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    return render(
        request,
        "turnos/editar_horario_disponible.html",
        {
            "form": form,
            "horario": horario,
            "max_ocupados": max_ocupados,
            "dia_nombre": dias[horario.dia_semana],
        },
    )


_WIZARD_ELIMINAR_HORARIO_KEY = "wizard_eliminar_horario"


def _wizard_eliminar_horario_get(request) -> dict:
    return request.session.get(_WIZARD_ELIMINAR_HORARIO_KEY, {})


def _wizard_eliminar_horario_set(request, data: dict):
    request.session[_WIZARD_ELIMINAR_HORARIO_KEY] = data
    request.session.modified = True


def _wizard_eliminar_horario_clear(request):
    request.session.pop(_WIZARD_ELIMINAR_HORARIO_KEY, None)


@login_required
@rol_requerido("admin")
def eliminar_horario_wizard_actividad(request):
    """Paso 1: elegir la actividad de la franja horaria a eliminar."""
    _wizard_eliminar_horario_clear(request)
    form = PasoActividadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _wizard_eliminar_horario_set(request, {"actividad_id": form.cleaned_data["actividad"].pk})
        return redirect("turnos:eliminar_horario_wizard_dia")
    return render(request, "turnos/eliminar_horario_wizard_actividad.html", {"form": form, "paso": 1})


@login_required
@rol_requerido("admin")
def eliminar_horario_wizard_dia(request):
    """Paso 2: elegir el día de la semana (solo se muestran días con franjas activas)."""
    wizard = _wizard_eliminar_horario_get(request)
    if "actividad_id" not in wizard:
        return redirect("turnos:eliminar_horario_wizard_actividad")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    dias_disponibles = list(
        HorarioDisponible.objects
        .filter(actividad=actividad, activo=True)
        .values_list("dia_semana", flat=True)
        .distinct()
    )
    if not dias_disponibles:
        messages.info(request, _("%(actividad)s no tiene franjas horarias activas.") % {"actividad": actividad})
        return redirect("turnos:eliminar_horario_wizard_actividad")

    form = EliminarHorarioDiaForm(request.POST or None, dias_disponibles=dias_disponibles)
    if request.method == "POST" and form.is_valid():
        wizard["dia_semana"] = form.cleaned_data["dia_semana"]
        _wizard_eliminar_horario_set(request, wizard)
        return redirect("turnos:eliminar_horario_wizard_franja")
    return render(request, "turnos/eliminar_horario_wizard_dia.html", {
        "form": form, "actividad": actividad, "paso": 2,
    })


@login_required
@rol_requerido("admin")
def eliminar_horario_wizard_franja(request):
    """Paso 3: elegir la franja horaria puntual. Al confirmar, va a la pantalla
    de aceptar/rechazar ya existente (`eliminar_horario_disponible`)."""
    wizard = _wizard_eliminar_horario_get(request)
    if "actividad_id" not in wizard or "dia_semana" not in wizard:
        return redirect("turnos:eliminar_horario_wizard_actividad")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    horarios_qs = HorarioDisponible.objects.filter(
        actividad=actividad, dia_semana=wizard["dia_semana"], activo=True
    ).order_by("hora")

    form = EliminarHorarioFranjaForm(request.POST or None, horarios_qs=horarios_qs)
    if request.method == "POST" and form.is_valid():
        horario = form.cleaned_data["horario"]
        _wizard_eliminar_horario_clear(request)
        return redirect("turnos:eliminar_horario_disponible", pk=horario.pk)
    return render(request, "turnos/eliminar_horario_wizard_franja.html", {
        "form": form, "actividad": actividad, "dia_nombre": dias[wizard["dia_semana"]], "paso": 3,
    })


@login_required
@rol_requerido("admin")
def eliminar_horario_disponible(request, pk):
    """
    Elimina una clase (HorarioDisponible) y cancela todos sus turnos futuros.

    Compensaciones por reserva cancelada:
    - PAGADO o abonado mensual → crédito gratis (otorgar_credito_cancelacion).
    - SEÑADO                   → email de reembolso pendiente.
    - PENDIENTE                → se cancela sin cargo.
    """
    from apps.creditos import services as creditos_services
    from .notificaciones import (
        enviar_aviso_cancelacion_clase,
        enviar_aviso_cancelacion_clase_credito,
        enviar_aviso_cancelacion_clase_por_club,
    )

    horario = get_object_or_404(HorarioDisponible, pk=pk)
    hoy = timezone.now().date()
    django_week_day = horario.dia_semana + 2

    # Turnos futuros de esta franja con reservas activas
    turnos_futuros = Turno.objects.filter(
        actividad=horario.actividad,
        hora=horario.hora,
        fecha__gte=hoy,
        fecha__week_day=django_week_day,
    ).prefetch_related("reservas__usuario")

    # Calcular impacto para mostrar en la pantalla de confirmación (GET) y ejecutar (POST)
    reservas_activas = []
    for turno in turnos_futuros:
        for reserva in turno.reservas.filter(
            estado=Reserva.Estado.CONFIRMADA
        ).select_related("usuario", "turno__actividad", "grupo_mensual"):
            reservas_activas.append(reserva)

    creditos_a_emitir = [
        r for r in reservas_activas
        if r.estado_pago == Reserva.EstadoPago.PAGADO or r.es_abonado_mensual
    ]
    reembolsos_pendientes = [
        r for r in reservas_activas
        if r.estado_pago == Reserva.EstadoPago.SENADO
    ]

    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    if request.method == "POST":
        with transaction.atomic():
            # Emitir créditos y notificar
            for reserva in creditos_a_emitir:
                credito = creditos_services.otorgar_credito_cancelacion(reserva)
                reserva.estado = Reserva.Estado.CANCELADA
                reserva.save(update_fields=["estado"])
                enviar_aviso_cancelacion_clase_credito(reserva, credito)

            # Reembolsos: cancelar y notificar
            for reserva in reembolsos_pendientes:
                monto = reserva.precio_abonado or 0
                reserva.estado = Reserva.Estado.CANCELADA
                reserva.save(update_fields=["estado"])
                enviar_aviso_cancelacion_clase_por_club(
                    reserva, "reembolso_sena", monto_reembolso=monto
                )

            # Cancelar el resto (PENDIENTE)
            for reserva in reservas_activas:
                if reserva.estado != Reserva.Estado.CANCELADA:
                    reserva.estado = Reserva.Estado.CANCELADA
                    reserva.save(update_fields=["estado"])

            horario.delete()

        return render(request, "turnos/eliminar_horario_resultado.html", {
            "creditos_emitidos": creditos_a_emitir,
            "reembolsos": reembolsos_pendientes,
            "sin_cargo": [r for r in reservas_activas if r not in creditos_a_emitir and r not in reembolsos_pendientes],
            "dia_nombre": dias[horario.dia_semana],
            "horario_str": str(horario),
        })

    return render(request, "turnos/eliminar_horario_confirm.html", {
        "horario": horario,
        "dia_nombre": dias[horario.dia_semana],
        "creditos_a_emitir": creditos_a_emitir,
        "reembolsos_pendientes": reembolsos_pendientes,
        "total_reservas": len(reservas_activas),
    })


# ── Cancelación de clase puntual (admin) ──────────────────────────────────────


def _horas_cancelacion_clase(actividad, fecha):
    horas = services.obtener_horas_disponibles(actividad, fecha)
    if fecha == timezone.now().date():
        hora_actual = timezone.now().hour
        horas = [h for h in horas if h["hora"] > hora_actual]
    return horas


def _datos_clase_desde_wizard_cancelar(request, wizard: dict):
    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha = date_type.fromisoformat(wizard["fecha"])
    hora = int(wizard["hora"])
    cancelacion_clase.validar_fecha_hora_futura(fecha, hora)
    turno = cancelacion_clase.buscar_turno_clase(actividad, fecha, hora)
    return actividad, fecha, hora, turno


@login_required
@rol_requerido("admin")
def cancelar_clase_paso_actividad(request):
    _wizard_cancelar_clear(request)
    form = AdminCancelarClaseActividadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _wizard_cancelar_set(request, {"actividad_id": form.cleaned_data["actividad"].pk})
        return redirect("cancelar_clase_fecha")
    return render(request, "turnos/cancelar_clase_paso_actividad.html", {"form": form, "paso": 1})


@login_required
@rol_requerido("admin")
def cancelar_clase_paso_fecha(request):
    wizard = _wizard_cancelar_get(request)
    if "actividad_id" not in wizard:
        return redirect("cancelar_clase_actividad")

    form = AdminCancelarClaseFechaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        wizard["fecha"] = form.cleaned_data["fecha"].isoformat()
        _wizard_cancelar_set(request, wizard)
        return redirect("cancelar_clase_hora")

    return render(
        request,
        "turnos/cancelar_clase_paso_fecha.html",
        {
            "form": form,
            "paso": 2,
            "actividad": get_object_or_404(Actividad, pk=wizard["actividad_id"]),
        },
    )


@login_required
@rol_requerido("admin")
def cancelar_clase_paso_hora(request):
    wizard = _wizard_cancelar_get(request)
    if "actividad_id" not in wizard or "fecha" not in wizard:
        return redirect("cancelar_clase_actividad")

    actividad = get_object_or_404(Actividad, pk=wizard["actividad_id"])
    fecha = date_type.fromisoformat(wizard["fecha"])
    horas_info = _horas_cancelacion_clase(actividad, fecha)

    if not horas_info:
        return render(
            request,
            "turnos/cancelar_clase_revisar.html",
            {"sin_clase": True, "sin_horarios": True, "actividad": actividad, "fecha": fecha},
        )

    form = AdminCancelarClaseHoraForm(request.POST or None, horas_info=horas_info, fecha=fecha)
    if request.method == "POST" and form.is_valid():
        wizard["hora"] = form.cleaned_data["hora"]
        _wizard_cancelar_set(request, wizard)
        return redirect("cancelar_clase_revisar")

    return render(
        request,
        "turnos/cancelar_clase_paso_hora.html",
        {"form": form, "paso": 3, "actividad": actividad, "fecha": fecha},
    )


@login_required
@rol_requerido("admin")
def cancelar_clase_revisar(request):
    wizard = _wizard_cancelar_get(request)
    if not all(k in wizard for k in ("actividad_id", "fecha", "hora")):
        return redirect("cancelar_clase_actividad")

    actividad, fecha, hora, turno = _datos_clase_desde_wizard_cancelar(request, wizard)
    sin_clase = turno is None
    impactos = cancelacion_clase.analizar_cancelacion(turno) if turno else []

    return render(
        request,
        "turnos/cancelar_clase_revisar.html",
        {
            "sin_clase": sin_clase,
            "actividad": actividad,
            "fecha": fecha,
            "hora": hora,
            "turno": turno,
            "impactos": impactos,
            "paso": 4,
        },
    )


@login_required
@rol_requerido("admin")
def cancelar_clase_confirmar(request):
    wizard = _wizard_cancelar_get(request)
    if not all(k in wizard for k in ("actividad_id", "fecha", "hora")):
        return redirect("cancelar_clase_actividad")

    actividad, fecha, hora, turno = _datos_clase_desde_wizard_cancelar(request, wizard)
    if turno is None:
        messages.error(
            request,
            _(
                "No se encontró ninguna clase para %(actividad)s el %(fecha)s a las %(hora)02d:00."
            )
            % {"actividad": actividad, "fecha": fecha.strftime("%d/%m/%Y"), "hora": hora},
        )
        return redirect("cancelar_clase_revisar")

    impactos = cancelacion_clase.analizar_cancelacion(turno)

    if request.method == "POST":
        cancelacion_clase.ejecutar_cancelacion_clase(turno)
        _wizard_cancelar_clear(request)
        messages.success(
            request,
            _(
                "La clase del %(fecha)s a las %(hora)02d:00 fue cancelada. Se notificó a %(n)d persona(s)."
            )
            % {"fecha": fecha.strftime("%d/%m/%Y"), "hora": hora, "n": len(impactos)},
        )
        return redirect("panel_turnos")

    return render(
        request,
        "turnos/cancelar_clase_confirmar.html",
        {"actividad": actividad, "fecha": fecha, "hora": hora, "impactos": impactos, "paso": 5},
    )