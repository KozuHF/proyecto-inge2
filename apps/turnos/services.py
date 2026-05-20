"""
Capa de servicios para la app turnos.

Concentra toda la lógica de negocio para crear y cancelar reservas,
manteniendo las vistas y modelos lo más delgados posible.
"""
import calendar
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from .models import (
    DIAS_HABILES,
    DIA_FIN_VENTANA_MENSUAL,
    DIA_INICIO_VENTANA_MENSUAL,
    GrupoReservaMensual,
    Reserva,
    Turno,
    _validar_dia_habil,
    _validar_hora,
    _validar_no_pasado,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fechas_del_dia_en_mes(dia_semana: int, anio: int, mes: int) -> list[date]:
    """
    Devuelve todas las fechas del mes `mes`/`anio` que caen en `dia_semana`
    (0=lunes … 5=sábado).
    """
    _, ultimo_dia = calendar.monthrange(anio, mes)
    fechas = []
    for d in range(1, ultimo_dia + 1):
        f = date(anio, mes, d)
        if f.weekday() == dia_semana:
            fechas.append(f)
    return fechas


def _obtener_o_crear_turno(actividad: Actividad, fecha: date, hora: int) -> Turno:
    """
    Obtiene el Turno existente o lo crea si no existe.
    Al crear, inicializa los cupos con el valor actual de la actividad.
    """
    turno, _ = Turno.objects.get_or_create(
        actividad=actividad,
        fecha=fecha,
        hora=hora,
        defaults={"cupos": actividad.cupos},
    )
    return turno


def _crear_reserva_para_turno(usuario, turno: Turno, tipo: str, grupo=None) -> Reserva:
    """
    Crea una Reserva para el turno dado.
    - Si hay cupos libres → CONFIRMADA.
    - Si está lleno → EN_ESPERA.
    Lanza ValidationError si el usuario ya tiene una reserva activa para ese turno.
    """
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


# ── Verificación de ventana mensual ──────────────────────────────────────────

def usuario_puede_reservar_mensual() -> bool:
    """
    Devuelve True si hoy está dentro de la ventana para reserva mensual
    (días 1 al 10 del mes en curso).
    """
    hoy = timezone.now().date()
    return DIA_INICIO_VENTANA_MENSUAL <= hoy.day <= DIA_FIN_VENTANA_MENSUAL


# ── Servicio principal: reserva individual ────────────────────────────────────

@transaction.atomic
def reservar_turno_individual(usuario, actividad: Actividad, fecha: date, hora: int) -> Reserva:
    """
    Crea una reserva individual para el usuario.
    Valida día hábil, hora válida y que la fecha no sea pasada.
    """
    _validar_no_pasado(fecha)
    _validar_dia_habil(fecha)
    _validar_hora(hora)

    turno   = _obtener_o_crear_turno(actividad, fecha, hora)
    reserva = _crear_reserva_para_turno(usuario, turno, Reserva.TipoReserva.INDIVIDUAL)
    return reserva


# ── Servicio principal: reserva mensual ──────────────────────────────────────

@transaction.atomic
def reservar_turno_mensual(usuario, actividad: Actividad, fecha_referencia: date, hora: int) -> GrupoReservaMensual:
    """
    Crea reservas para todos los turnos del mes que coincidan con el mismo
    día de la semana y hora que `fecha_referencia`.

    Solo disponible si hoy está entre el 1 y el 10 del mes.

    Devuelve el GrupoReservaMensual creado.
    Las reservas individuales están accesibles via grupo.reservas.all().
    """
    if not usuario_puede_reservar_mensual():
        raise ValidationError(
            _("La reserva mensual solo está disponible entre el %(inicio)s y el %(fin)s de cada mes.")
            % {"inicio": DIA_INICIO_VENTANA_MENSUAL, "fin": DIA_FIN_VENTANA_MENSUAL}
        )

    _validar_dia_habil(fecha_referencia)
    _validar_hora(hora)

    hoy         = timezone.now().date()
    anio        = hoy.year
    mes         = hoy.month
    dia_semana  = fecha_referencia.weekday()

    fechas = _fechas_del_dia_en_mes(dia_semana, anio, mes)
    # Solo fechas que no hayan pasado
    fechas = [f for f in fechas if f >= hoy]

    if not fechas:
        raise ValidationError(_("No quedan fechas disponibles en el mes para ese día y horario."))

    grupo = GrupoReservaMensual.objects.create(
        usuario=usuario,
        actividad=actividad,
        dia_semana=dia_semana,
        hora=hora,
        anio=anio,
        mes=mes,
    )

    errores = []
    for fecha in fechas:
        turno = _obtener_o_crear_turno(actividad, fecha, hora)
        try:
            _crear_reserva_para_turno(usuario, turno, Reserva.TipoReserva.MENSUAL, grupo=grupo)
        except ValidationError as e:
            errores.append(str(e))

    # Si falló todo (p.ej. ya tenía todas las reservas), eliminar el grupo vacío
    if not grupo.reservas.exists():
        grupo.delete()
        raise ValidationError(
            _("No se pudo crear ninguna reserva del mes. %(detalle)s") % {"detalle": " | ".join(errores)}
        )

    return grupo


# ── Cancelación ───────────────────────────────────────────────────────────────

@transaction.atomic
def cancelar_reserva(usuario, reserva_id: int) -> Reserva:
    """
    Cancela una reserva perteneciente al usuario.
    Lanza ValidationError si la reserva no le pertenece o ya está cancelada.
    """
    try:
        reserva = Reserva.objects.select_related("turno", "turno__actividad").get(
            pk=reserva_id, usuario=usuario
        )
    except Reserva.DoesNotExist:
        raise ValidationError(_("Reserva no encontrada."))

    reserva.cancelar()
    return reserva


@transaction.atomic
def cancelar_grupo_mensual(usuario, grupo_id: int) -> GrupoReservaMensual:
    """
    Cancela todas las reservas activas de un grupo mensual perteneciente al usuario.
    """
    try:
        grupo = GrupoReservaMensual.objects.get(pk=grupo_id, usuario=usuario)
    except GrupoReservaMensual.DoesNotExist:
        raise ValidationError(_("Grupo de reserva mensual no encontrado."))

    grupo.cancelar_todo()
    return grupo


# ── Consultas de apoyo para las vistas ───────────────────────────────────────

def obtener_horas_disponibles(actividad: Actividad, fecha: date) -> list[dict]:
    """
    Devuelve la lista de horas del día con su disponibilidad para una
    actividad y fecha dadas.

    Cada elemento: {"hora": int, "libres": int, "lleno": bool, "en_espera": int}
    """
    from .models import HORAS_VALIDAS

    turnos_existentes = {
        t.hora: t
        for t in Turno.objects.filter(actividad=actividad, fecha=fecha)
    }

    resultado = []
    for hora in HORAS_VALIDAS:
        turno = turnos_existentes.get(hora)
        if turno:
            libres    = turno.cupos_libres
            lleno     = turno.esta_lleno
            en_espera = turno.lista_espera.count()
        else:
            libres    = actividad.cupos
            lleno     = False
            en_espera = 0

        resultado.append({
            "hora":      hora,
            "libres":    libres,
            "lleno":     lleno,
            "en_espera": en_espera,
        })
    return resultado