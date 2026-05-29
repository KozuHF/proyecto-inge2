"""
Capa de servicios para la app turnos.

Concentra toda la lógica de negocio para crear y cancelar reservas,
manteniendo las vistas y modelos lo más delgados posible.
"""
import calendar
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from .abono_mensual import (
    REGLA_PRIMERA_QUINCENA,
    monto_total_desde_fechas,
    plazo_pago_vencido,
)
from .models import (
    MODO_TURNO_UNICO,
    MODO_VARIOS_TURNOS,
    GrupoReservaMensual,
    Reserva,
    Turno,
    _validar_dia_habil,
    _validar_hora,
    _validar_no_pasado,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fechas_del_dia_en_mes(dia_semana: int, anio: int, mes: int) -> list[date]:
    """Todas las fechas del mes que caen en `dia_semana` (0=lunes … 5=sábado)."""
    _, ultimo_dia = calendar.monthrange(anio, mes)
    fechas = []
    for d in range(1, ultimo_dia + 1):
        f = date(anio, mes, d)
        if f.weekday() == dia_semana:
            fechas.append(f)
    return fechas


def _obtener_o_crear_turno(actividad: Actividad, fecha: date, hora: int) -> Turno:
    turno, _ = Turno.objects.get_or_create(
        actividad=actividad,
        fecha=fecha,
        hora=hora,
        defaults={"cupos": actividad.cupos},
    )
    return turno


def generar_turnos_desde_horario(horario, meses: int = 120) -> tuple[int, int]:
    """
    Genera los objetos Turno para los próximos `meses` meses a partir de hoy,
    según el HorarioDisponible recibido.

    Salta fechas pasadas, feriados inamovibles y domingos.
    No toca turnos que ya existen (usa get_or_create).

    Devuelve (creados, omitidos) donde:
      - creados  = turnos nuevos insertados en BD
      - omitidos = fechas que ya tenían turno o eran inválidas
    """
    from .models import FERIADOS_INAMOVIBLES, DIAS_HABILES

    hoy = timezone.now().date()
    # Calcular fecha límite: hoy + 6 meses completos
    mes_fin = hoy.month + meses
    anio_fin = hoy.year + (mes_fin - 1) // 12
    mes_fin = (mes_fin - 1) % 12 + 1
    _, ultimo = calendar.monthrange(anio_fin, mes_fin)
    fecha_fin = date(anio_fin, mes_fin, ultimo)

    cupos = horario.cupos_efectivos()
    creados = 0
    omitidos = 0

    # Iterar semana a semana desde la primera ocurrencia del día elegido
    # a partir de hoy hasta fecha_fin.
    dias_hasta = (horario.dia_semana - hoy.weekday()) % 7
    primera = hoy + __import__("datetime").timedelta(days=dias_hasta)

    fecha_actual = primera
    delta = __import__("datetime").timedelta(weeks=1)

    while fecha_actual <= fecha_fin:
        # Saltar feriados inamovibles
        if (fecha_actual.month, fecha_actual.day) in FERIADOS_INAMOVIBLES:
            omitidos += 1
            fecha_actual += delta
            continue

        _, created = Turno.objects.get_or_create(
            actividad=horario.actividad,
            fecha=fecha_actual,
            hora=horario.hora,
            defaults={"cupos": cupos, "precio_override": horario.precio},
        )
        if created:
            creados += 1
        else:
            omitidos += 1

        fecha_actual += delta

    return creados, omitidos


def _crear_reserva_para_turno(usuario, turno: Turno, tipo: str, grupo=None) -> Reserva:
    ya_existe = Reserva.objects.filter(
        usuario=usuario,
        turno=turno,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
    ).exists()
    if ya_existe:
        raise ValidationError(
            _("Ya tenés una reserva activa para el turno %(turno)s.") % {"turno": turno}
        )

    estado = Reserva.Estado.EN_ESPERA if turno.esta_lleno else Reserva.Estado.CONFIRMADA

    return Reserva.objects.create(
        usuario=usuario,
        turno=turno,
        estado=estado,
        tipo_reserva=tipo,
        grupo_mensual=grupo,
    )


# ── Fechas candidatas para «varios turnos» ────────────────────────────────────

def obtener_fechas_candidatas_varios(fecha_referencia: date, hora: int, actividad=None) -> list[date]:
    """
    Devuelve las fechas del mes de `fecha_referencia` con el mismo día de la semana,
    en el horario dado, excluyendo fechas pasadas y días no hábiles.

    Si se provee `actividad`, verifica además que exista un HorarioDisponible
    activo para esa actividad/día/hora antes de devolver las fechas.
    """
    from .models import HorarioDisponible

    _validar_dia_habil(fecha_referencia)
    _validar_hora(hora)

    # Verificar que el horario esté habilitado por el admin
    if actividad is not None:
        horario_existe = HorarioDisponible.objects.filter(
            actividad=actividad,
            dia_semana=fecha_referencia.weekday(),
            hora=hora,
            activo=True,
        ).exists()
        if not horario_existe:
            raise ValidationError(
                _("El horario seleccionado no está disponible para esta actividad.")
            )

    hoy = timezone.now().date()
    anio = fecha_referencia.year
    mes = fecha_referencia.month
    fechas = _fechas_del_dia_en_mes(fecha_referencia.weekday(), anio, mes)

    valid_fechas = []
    for f in fechas:
        if f >= hoy:
            try:
                _validar_dia_habil(f)
                valid_fechas.append(f)
            except ValidationError:
                pass
    fechas = valid_fechas

    if not fechas:
        raise ValidationError(
            _("No quedan fechas disponibles en %(mes)s/%(anio)s para ese día y horario.")
            % {"mes": mes, "anio": anio}
        )

    return fechas


def _validar_fechas_seleccionadas(
    fechas_seleccionadas: list[date],
    fecha_referencia: date,
    hora: int,
    actividad=None,
) -> list[date]:
    candidatas = set(obtener_fechas_candidatas_varios(fecha_referencia, hora, actividad=actividad))
    invalidas = [f for f in fechas_seleccionadas if f not in candidatas]
    if invalidas:
        raise ValidationError(_("Hay fechas seleccionadas que no son válidas."))
    if not fechas_seleccionadas:
        raise ValidationError(_("Seleccioná al menos un día."))
    for f in fechas_seleccionadas:
        _validar_dia_habil(f)
        _validar_no_pasado(f)
    return sorted(fechas_seleccionadas)


# ── Cálculo de montos (antes de crear la reserva) ─────────────────────────────

def calcular_monto_reserva_nueva(
    actividad: Actividad,
    modo: str,
    fecha: date,
    hora: int,
    fechas_seleccionadas: list[date] | None = None,
    usuario=None,
):
    """Devuelve (monto_total, cantidad_turnos)."""
    from decimal import Decimal

    if modo == MODO_TURNO_UNICO:
        _validar_no_pasado(fecha)
        _validar_dia_habil(fecha)
        _validar_hora(hora)
        return actividad.precio_turno, 1

    if modo == MODO_VARIOS_TURNOS:
        if not fechas_seleccionadas:
            raise ValidationError(_("Seleccioná al menos un día para reservar."))
        fechas = _validar_fechas_seleccionadas(fechas_seleccionadas, fecha, hora, actividad=actividad)
        total, _, _ = monto_total_desde_fechas(
            actividad, fechas, usuario=usuario, anio=fecha.year, mes=fecha.month
        )
        return total, len(fechas)

    raise ValidationError(_("Modo de reserva no válido."))


# ── Creación de reservas ────────────────────────────────────────────────────────

@transaction.atomic
def reservar_turno_individual(usuario, actividad: Actividad, fecha: date, hora: int) -> Reserva:
    _validar_no_pasado(fecha)
    _validar_dia_habil(fecha)
    _validar_hora(hora)

    turno = _obtener_o_crear_turno(actividad, fecha, hora)
    return _crear_reserva_para_turno(usuario, turno, Reserva.TipoReserva.INDIVIDUAL)


@transaction.atomic
def reservar_varios_turnos(
    usuario,
    actividad: Actividad,
    hora: int,
    fechas_seleccionadas: list[date],
    fecha_referencia: date,
) -> GrupoReservaMensual:
    """
    Crea reservas solo para las fechas que el usuario eligió.
    """
    fechas = _validar_fechas_seleccionadas(fechas_seleccionadas, fecha_referencia, hora, actividad=actividad)
    _, regla_cobro, descuento = monto_total_desde_fechas(
        actividad,
        fechas,
        usuario=usuario,
        anio=fecha_referencia.year,
        mes=fecha_referencia.month,
    )

    grupo = GrupoReservaMensual.objects.create(
        usuario=usuario,
        actividad=actividad,
        dia_semana=fecha_referencia.weekday(),
        hora=hora,
        anio=fecha_referencia.year,
        mes=fecha_referencia.month,
        regla_cobro=regla_cobro,
        descuento_porcentaje=descuento * 100,
    )

    errores = []
    for fecha in fechas:
        turno = _obtener_o_crear_turno(actividad, fecha, hora)
        try:
            _crear_reserva_para_turno(
                usuario, turno, Reserva.TipoReserva.VARIOS, grupo=grupo
            )
        except ValidationError as e:
            errores.append(str(e))

    if not grupo.reservas.exists():
        grupo.delete()
        raise ValidationError(
            _("No se pudo crear ninguna reserva. %(detalle)s")
            % {"detalle": " | ".join(errores) if errores else ""}
        )

    return grupo


# ── Cancelación ───────────────────────────────────────────────────────────────

@transaction.atomic
def cancelar_reserva(usuario, reserva_id: int) -> tuple[Reserva, bool]:
    from apps.creditos import services as creditos_services

    try:
        reserva = Reserva.objects.select_related("turno", "turno__actividad").get(
            pk=reserva_id, usuario=usuario
        )
    except Reserva.DoesNotExist:
        raise ValidationError(_("Reserva no encontrada."))

    from .penalidad_cancelaciones import registrar_cancelacion_abono_mensual

    otorgar_credito = creditos_services.puede_otorgar_credito_cancelacion(reserva)
    era_abono = reserva.es_abonado_mensual
    reserva.cancelar()

    if era_abono:
        registrar_cancelacion_abono_mensual(reserva)

    if otorgar_credito:
        creditos_services.otorgar_credito_cancelacion(reserva)

    return reserva, otorgar_credito


@transaction.atomic
def cancelar_grupo_mensual(usuario, grupo_id: int) -> tuple[GrupoReservaMensual, int]:
    from apps.creditos import services as creditos_services

    try:
        grupo = (
            GrupoReservaMensual.objects
            .prefetch_related("reservas__turno__actividad")
            .get(pk=grupo_id, usuario=usuario)
        )
    except GrupoReservaMensual.DoesNotExist:
        raise ValidationError(_("Grupo de reserva no encontrado."))

    reservas_activas = list(
        grupo.reservas.filter(
            estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA]
        ).select_related("turno", "turno__actividad")
    )
    from .penalidad_cancelaciones import registrar_cancelacion_abono_mensual

    reservas_con_credito = [
        r for r in reservas_activas
        if creditos_services.puede_otorgar_credito_cancelacion(r)
    ]

    for reserva in reservas_activas:
        registrar_cancelacion_abono_mensual(reserva)

    grupo.cancelar_todo()

    creditos_otorgados = creditos_services.otorgar_creditos_por_cancelacion_grupo(
        reservas_con_credito
    )
    return grupo, creditos_otorgados


def reservas_futuras_de_usuario(usuario):
    """
    Devuelve las reservas activas (confirmadas o en espera) del usuario
    cuyo turno todavía no ocurrió.
    """
    hoy = timezone.now().date()
    return (
        Reserva.objects
        .filter(
            usuario=usuario,
            estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
            turno__fecha__gte=hoy,
        )
        .select_related("turno")
    )


@transaction.atomic
def cancelar_reservas_futuras_de_usuario(usuario) -> int:
    """
    Cancela todas las reservas futuras del usuario, promoviendo la lista
    de espera de cada turno liberado. Devuelve la cantidad cancelada.
    """
    reservas = list(reservas_futuras_de_usuario(usuario))
    for reserva in reservas:
        reserva.cancelar()
    return len(reservas)


# ── Consultas de apoyo para las vistas ───────────────────────────────────────

def obtener_horas_disponibles(actividad, fecha) -> list[dict]:
    """
    Devuelve los bloques horarios disponibles para reservar en una fecha dada.

    Solo se incluyen horas que el admin habilitó mediante un HorarioDisponible
    activo para esa actividad y ese día de la semana.  Si el turno físico ya
    existe en BD se usa su información; si no existe aún se crea al momento de
    confirmar la reserva (en _obtener_o_crear_turno).
    """
    from .models import HorarioDisponible

    dia_semana = fecha.weekday()

    # Horarios que el admin definió para este día de la semana
    horarios = (
        HorarioDisponible.objects
        .filter(actividad=actividad, dia_semana=dia_semana, activo=True)
        .order_by("hora")
    )

    # Turnos físicos que ya existen para esta fecha
    turnos_existentes = {
        t.hora: t
        for t in Turno.objects.filter(actividad=actividad, fecha=fecha)
    }

    resultado = []
    for horario in horarios:
        hora = horario.hora
        turno = turnos_existentes.get(hora)
        if turno:
            libres    = turno.cupos_libres
            lleno     = turno.esta_lleno
            en_espera = turno.lista_espera.count()
        else:
            libres    = horario.cupos_efectivos()
            lleno     = False
            en_espera = 0

        resultado.append({
            "hora":      hora,
            "libres":    libres,
            "lleno":     lleno,
            "en_espera": en_espera,
        })
    return resultado


# ── Plazos y suspensión (abono mensual) ───────────────────────────────────────

@transaction.atomic
def aplicar_sancion_plazo_vencido(grupo: GrupoReservaMensual) -> bool:
    """
    Cancela el abono y suspende al usuario si venció el plazo del día 11.
    Devuelve True si se aplicó la sanción.
    """
    if not plazo_pago_vencido(grupo):
        return False

    if grupo.cantidad_turnos_activos:
        grupo.cancelar_todo()

    usuario = grupo.usuario
    if not usuario.suspendido:
        usuario.suspendido = True
        usuario.save(update_fields=["suspendido"])

    return True


def verificar_plazos_abonos_mensuales(usuario=None) -> int:
    """
    Revisa abonos de primera quincena impagos tras el día 11 y aplica sanciones.
    Devuelve la cantidad de sanciones aplicadas.
    """
    grupos = (
        GrupoReservaMensual.objects
        .select_related("usuario")
        .prefetch_related("reservas__turno")
    )
    if usuario is not None:
        grupos = grupos.filter(usuario=usuario)

    sanciones = 0
    for grupo in grupos:
        if (
            grupo.cantidad_turnos_activos
            and grupo.incluye_turnos_dia_1_a_10
            and aplicar_sancion_plazo_vencido(grupo)
        ):
            sanciones += 1
    return sanciones


def usuario_puede_reservar(usuario) -> bool:
    return not getattr(usuario, "suspendido", False)