"""
Gateway de pago simulado para demostración académica.

Tarjetas de demostración (solo uso interno del equipo):
  - 0602 2004 3007 1971 → pago aprobado
  - 1509 2000 0106 1970 → rechazado por fondos insuficientes
"""
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from apps.creditos import services as creditos_services
from apps.creditos.services import ContextoPagoCreditos
from apps.turnos import services as turnos_services
from apps.turnos.abono_mensual import (
    clasificar_regla_abono,
    permite_pago_sena,
    requiere_pago_antes_dia_11,
)
from apps.turnos.models import (
    GrupoReservaMensual,
    MODO_TURNO_UNICO,
    MODO_VARIOS_TURNOS,
    Reserva,
)

from . import tarjetas
from .models import Pago

FRACCION_SENA = Decimal("0.5")
WIZARD_KEY = "wizard_reserva"

TIPO_TOTAL = "total"
TIPO_SENA = "sena"
TIPO_SALDO = "saldo"

TARJETAS_DEMO = {
    "0602200430071971": {"tiene_fondos": True},
    "1509200001061970": {"tiene_fondos": False},
}


@dataclass
class ResultadoPago:
    exito: bool
    pago: Pago | None = None
    mensaje: str = ""
    reserva: Reserva | None = None
    reservas_creadas: int = 0


@dataclass
class DatosCheckout:
    actividad: Actividad
    fecha: date_type
    hora: int
    modo: str
    monto_total: Decimal
    cantidad_turnos: int
    fechas_seleccionadas: list[date_type] | None = None
    regla_cobro: str | None = None
    permite_sena: bool = True


def normalizar_numero_tarjeta(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def ultimos_4_digitos(numero: str) -> str:
    pan = normalizar_numero_tarjeta(numero)
    return pan[-4:] if len(pan) >= 4 else pan


def monto_seña(total: Decimal) -> Decimal:
    return (total * FRACCION_SENA).quantize(Decimal("0.01"))


def monto_total_reserva(reserva: Reserva) -> Decimal:
    return reserva.monto_total


def datos_desde_wizard(wizard: dict, usuario=None) -> DatosCheckout:
    requeridos = ("modo", "actividad_id", "fecha", "hora")
    if not all(k in wizard for k in requeridos):
        raise ValidationError(_("Datos de reserva incompletos. Volvé a iniciar el proceso."))

    try:
        actividad = Actividad.objects.get(pk=wizard["actividad_id"])
    except Actividad.DoesNotExist:
        raise ValidationError(_("Actividad no encontrada."))

    fecha = date_type.fromisoformat(wizard["fecha"])
    hora = int(wizard["hora"])
    modo = wizard["modo"]

    fechas_sel = None
    if modo == MODO_VARIOS_TURNOS:
        if "fechas_seleccionadas" not in wizard:
            raise ValidationError(_("Seleccioná los días que querés reservar."))
        fechas_sel = [date_type.fromisoformat(f) for f in wizard["fechas_seleccionadas"]]

    monto_total, cantidad = turnos_services.calcular_monto_reserva_nueva(
        actividad,
        modo,
        fecha,
        hora,
        fechas_seleccionadas=fechas_sel,
        usuario=usuario,
    )

    regla_cobro = None
    if modo == MODO_VARIOS_TURNOS and fechas_sel:
        from apps.turnos.abono_mensual import monto_total_desde_fechas

        _, regla_cobro, _ = monto_total_desde_fechas(
            actividad, fechas_sel, usuario=usuario, anio=fecha.year, mes=fecha.month
        )

    return DatosCheckout(
        actividad=actividad,
        fecha=fecha,
        hora=hora,
        modo=modo,
        monto_total=monto_total,
        cantidad_turnos=cantidad,
        fechas_seleccionadas=fechas_sel,
        regla_cobro=regla_cobro,
        permite_sena=permite_pago_sena(regla_cobro) if regla_cobro else True,
    )


def opciones_pago_nueva_reserva(
    monto_total: Decimal,
    *,
    permite_sena: bool = True,
) -> list[tuple[str, str, Decimal]]:
    opciones = [(TIPO_TOTAL, _("Pagar total"), monto_total)]
    if permite_sena:
        opciones.append((TIPO_SENA, _("Pagar seña (50%)"), monto_seña(monto_total)))
    return opciones


def opciones_pago_nueva_desde_checkout(datos: DatosCheckout) -> list[tuple[str, str, Decimal]]:
    return opciones_pago_nueva_reserva(
        datos.monto_total,
        permite_sena=datos.permite_sena,
    )


def opciones_pago_reserva(reserva: Reserva) -> list[tuple[str, str, Decimal]]:
    total = monto_total_reserva(reserva)

    if reserva.estado_pago == Reserva.EstadoPago.PENDIENTE:
        return opciones_pago_nueva_reserva(total)

    if reserva.estado_pago == Reserva.EstadoPago.SENADO:
        return [
            (TIPO_SALDO, _("Completar pago (saldo)"), reserva.monto_saldo),
        ]

    return []


def calcular_monto_cobro_reserva(reserva: Reserva, tipo_pago: str) -> Decimal:
    opciones = {op[0]: op[2] for op in opciones_pago_reserva(reserva)}
    if tipo_pago not in opciones:
        raise ValidationError(_("Opción de pago no válida para esta reserva."))
    return opciones[tipo_pago]


def calcular_monto_cobro_nueva(datos: DatosCheckout, tipo_pago: str) -> Decimal:
    opciones = {op[0]: op[2] for op in opciones_pago_nueva_desde_checkout(datos)}
    if tipo_pago not in opciones:
        raise ValidationError(_("Opción de pago no válida."))
    return opciones[tipo_pago]


def obtener_grupo_pagable(usuario, grupo_id: int) -> GrupoReservaMensual:
    turnos_services.verificar_plazos_abonos_mensuales(usuario)

    try:
        grupo = (
            GrupoReservaMensual.objects
            .select_related("actividad")
            .prefetch_related("reservas__turno__actividad")
            .get(pk=grupo_id, usuario=usuario)
        )
    except GrupoReservaMensual.DoesNotExist:
        raise ValidationError(_("Abonado mensual no encontrado."))

    if not grupo.cantidad_turnos_activos:
        raise ValidationError(_("Este abono mensual no tiene turnos activos."))

    if requiere_pago_antes_dia_11(grupo.regla_cobro) and turnos_services.aplicar_sancion_plazo_vencido(grupo):
        raise ValidationError(
            _("El plazo de pago venció el día 11. Se cancelaron los turnos y tu cuenta fue suspendida.")
        )

    if not grupo.puede_pagar_grupo:
        raise ValidationError(_("Este abono mensual ya está pagado."))

    return grupo


def opciones_pago_grupo(grupo: GrupoReservaMensual) -> list[tuple[str, str, Decimal]]:
    if grupo.estado_pago_agregado == Reserva.EstadoPago.PENDIENTE:
        total = grupo.monto_total_grupo
        opciones = [(TIPO_TOTAL, _("Pagar total del abono"), total)]
        if grupo.permite_pago_sena:
            opciones.append(
                (TIPO_SENA, _("Pagar seña del abono (50%)"), monto_seña(total))
            )
        return opciones
    if grupo.estado_pago_agregado == Reserva.EstadoPago.SENADO:
        if not grupo.permite_pago_sena:
            return []
        return [
            (TIPO_SALDO, _("Completar pago del abono"), grupo.monto_saldo_grupo),
        ]
    return []


def calcular_monto_cobro_grupo(grupo: GrupoReservaMensual, tipo_pago: str) -> Decimal:
    opciones = {op[0]: op[2] for op in opciones_pago_grupo(grupo)}
    if tipo_pago not in opciones:
        raise ValidationError(_("Opción de pago no válida para este abono mensual."))
    return opciones[tipo_pago]


def obtener_reserva_pagable(usuario, reserva_id: int) -> Reserva:
    try:
        reserva = (
            Reserva.objects
            .select_related("turno", "turno__actividad")
            .get(
                pk=reserva_id,
                usuario=usuario,
                estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
            )
        )
    except Reserva.DoesNotExist:
        raise ValidationError(_("Reserva no encontrada o no disponible para pago."))

    if reserva.estado_pago == Reserva.EstadoPago.PAGADO:
        raise ValidationError(_("Esta reserva ya está pagada."))

    if reserva.es_abonado_mensual:
        raise ValidationError(
            _("El pago de este turno se gestiona desde el abono mensual.")
        )

    if not opciones_pago_reserva(reserva):
        raise ValidationError(_("No hay opciones de pago disponibles para esta reserva."))

    return reserva


def _validar_no_sena_con_creditos(tipo_pago: str, creditos_usados: int) -> None:
    if creditos_usados > 0 and tipo_pago == TIPO_SENA:
        raise ValidationError(
            _("No podés pagar seña si usás créditos. Elegí pago total o no uses créditos.")
        )


def _preparar_cobro_con_creditos(
    usuario,
    ctx: ContextoPagoCreditos | None,
    creditos_usados: int,
    monto_cobro: Decimal,
    *,
    tipo_pago: str | None = None,
) -> tuple[Decimal, Decimal, int]:
    if creditos_usados > 0 and tipo_pago:
        _validar_no_sena_con_creditos(tipo_pago, creditos_usados)
    if not ctx or creditos_usados <= 0:
        return monto_cobro, Decimal("0"), 0
    return creditos_services.validar_creditos_pago(
        usuario,
        ctx.actividad,
        creditos_usados,
        ctx.max_creditos,
        monto_cobro,
        ctx.regla_cobro,
        valor_credito=ctx.valor_credito,
    )


def _validar_tarjeta(
    numero_tarjeta: str,
    ultimos: str,
    monto: Decimal,
    tipo_pago: str,
    usuario,
    reserva=None,
    *,
    cvv: str = "",
) -> ResultadoPago:
    if monto <= 0:
        return ResultadoPago(exito=True)

    pan = normalizar_numero_tarjeta(numero_tarjeta)

    def _rechazar(motivo: str, mensaje: str) -> ResultadoPago:
        pago = Pago.objects.create(
            reserva=reserva,
            usuario=usuario,
            monto=monto,
            estado=Pago.Estado.RECHAZADO,
            tipo_cobro=tipo_pago,
            ultimos_4=ultimos or "0000",
            motivo_rechazo=motivo,
        )
        return ResultadoPago(exito=False, pago=pago, mensaje=mensaje)

    if len(pan) != 16:
        return _rechazar(
            _("Número de tarjeta inválido."),
            _("Número de tarjeta inválido. Debe tener 16 dígitos."),
        )

    try:
        tarjetas.validar_cvv(cvv or "")
    except ValidationError:
        return _rechazar(
            str(tarjetas.MENSAJE_CVV_INCORRECTO),
            str(tarjetas.MENSAJE_CVV_INCORRECTO),
        )

    if not tarjetas.es_pan_demo(pan):
        return _rechazar(
            _("Tarjeta no habilitada en modo demostración."),
            _("Tarjeta no válida para esta demostración."),
        )

    if not tarjetas.pan_tiene_fondos(pan):
        return _rechazar(
            _("Fondos insuficientes."),
            _("Pago rechazado: fondos insuficientes."),
        )

    return ResultadoPago(exito=True)


def _aplicar_pago_aprobado(reserva: Reserva, tipo_pago: str, monto_cobrado: Decimal, referencia: str):
    total = reserva.monto_total

    if tipo_pago == TIPO_SENA:
        reserva.estado_pago = Reserva.EstadoPago.SENADO
        reserva.precio_abonado = monto_cobrado
    else:
        reserva.estado_pago = Reserva.EstadoPago.PAGADO
        reserva.precio_abonado = total

    reserva.referencia_pago = referencia
    reserva.save(update_fields=["estado_pago", "referencia_pago", "precio_abonado"])


def _aplicar_pago_a_reservas(reservas, tipo_pago: str, monto_cobrado: Decimal, referencia: str):
    for reserva in reservas:
        if tipo_pago == TIPO_SENA:
            monto_reserva = monto_seña(reserva.monto_total)
            _aplicar_pago_aprobado(reserva, TIPO_SENA, monto_reserva, referencia)
        else:
            _aplicar_pago_aprobado(reserva, tipo_pago, reserva.monto_total, referencia)


def _mensaje_exito(
    tipo_pago: str,
    monto: Decimal,
    referencia: str,
    en_espera: bool = False,
    *,
    creditos_usados: int = 0,
    descuento_creditos: Decimal | None = None,
) -> str:
    base = ""
    if tipo_pago == TIPO_SENA:
        base = _("Seña abonada ($%(monto)s). Referencia: %(ref)s") % {"monto": monto, "ref": referencia}
    elif tipo_pago == TIPO_SALDO:
        base = _("Reserva totalmente abonada. Referencia: %(ref)s") % {"ref": referencia}
    else:
        base = _("Pago total realizado. Referencia: %(ref)s") % {"ref": referencia}

    if creditos_usados:
        desc = descuento_creditos or Decimal("0")
        base += " " + _(
            "Se usaron %(n)d crédito(s) ($%(desc)s de descuento)."
        ) % {"n": creditos_usados, "desc": desc}

    if en_espera:
        base += " " + _("Quedaste en lista de espera para el turno.")
    return base


def _ultimos_4_o_creditos(numero_tarjeta: str, creditos_usados: int) -> str:
    if creditos_usados and not numero_tarjeta:
        return "CRDT"
    return ultimos_4_digitos(numero_tarjeta)


@transaction.atomic
def procesar_pago_y_reservar(
    usuario,
    wizard: dict,
    numero_tarjeta: str,
    tipo_pago: str,
    creditos_usados: int = 0,
    *,
    cvv: str = "",
) -> ResultadoPago:
    """
    Valida el pago y, solo si es aprobado, crea la reserva (o el grupo mensual).
    Si el pago falla, no se crea ningún turno reservado.
    """
    datos = datos_desde_wizard(wizard, usuario)
    if not turnos_services.usuario_puede_reservar(usuario):
        raise ValidationError(_("Tu cuenta está suspendida. No podés realizar reservas."))
    monto_cobro = calcular_monto_cobro_nueva(datos, tipo_pago)
    ctx = creditos_services.contexto_desde_checkout(usuario, datos)
    monto_tarjeta, descuento, creditos_efectivos = _preparar_cobro_con_creditos(
        usuario, ctx, creditos_usados, monto_cobro, tipo_pago=tipo_pago
    )
    ultimos = _ultimos_4_o_creditos(numero_tarjeta, creditos_efectivos)

    resultado_tarjeta = _validar_tarjeta(
        numero_tarjeta, ultimos, monto_tarjeta, tipo_pago, usuario, reserva=None, cvv=cvv
    )
    if not resultado_tarjeta.exito:
        return resultado_tarjeta

    creditos_services.consumir_creditos(
        usuario, datos.actividad, creditos_efectivos
    )

    referencia = Pago.generar_referencia()
    en_espera = False

    if datos.modo == MODO_VARIOS_TURNOS:
        grupo = turnos_services.reservar_varios_turnos(
            usuario,
            datos.actividad,
            datos.hora,
            datos.fechas_seleccionadas,
            datos.fecha,
        )
        reservas = list(grupo.reservas.select_related("turno", "turno__actividad"))
        _aplicar_pago_a_reservas(reservas, tipo_pago, monto_cobro, referencia)
        reserva_principal = reservas[0]
        reservas_creadas = len(reservas)
        en_espera = any(r.estado == Reserva.Estado.EN_ESPERA for r in reservas)
        mensaje = _(
            "Reservaste %(n)d turnos. %(detalle)s"
        ) % {
            "n": reservas_creadas,
            "detalle": _mensaje_exito(
                tipo_pago,
                monto_tarjeta,
                referencia,
                en_espera,
                creditos_usados=creditos_efectivos,
                descuento_creditos=descuento,
            ),
        }
    else:
        reserva = turnos_services.reservar_turno_individual(
            usuario, datos.actividad, datos.fecha, datos.hora
        )
        monto_reserva = monto_seña(reserva.monto_total) if tipo_pago == TIPO_SENA else reserva.monto_total
        _aplicar_pago_aprobado(reserva, tipo_pago, monto_reserva, referencia)
        reserva_principal = reserva
        reservas_creadas = 1
        en_espera = reserva.estado == Reserva.Estado.EN_ESPERA
        mensaje = _mensaje_exito(
            tipo_pago,
            monto_tarjeta,
            referencia,
            en_espera,
            creditos_usados=creditos_efectivos,
            descuento_creditos=descuento,
        )
        if not en_espera:
            mensaje = _("Reserva confirmada. ") + mensaje

    Pago.objects.create(
        reserva=reserva_principal,
        usuario=usuario,
        monto=monto_tarjeta,
        estado=Pago.Estado.APROBADO,
        tipo_cobro=tipo_pago,
        referencia=referencia,
        ultimos_4=ultimos,
        creditos_usados=creditos_efectivos,
    )

    return ResultadoPago(
        exito=True,
        pago=None,
        mensaje=mensaje,
        reserva=reserva_principal,
        reservas_creadas=reservas_creadas,
    )


@transaction.atomic
def procesar_pago_reserva(
    usuario,
    reserva_id: int,
    numero_tarjeta: str,
    tipo_pago: str,
    creditos_usados: int = 0,
    *,
    cvv: str = "",
) -> ResultadoPago:
    """Pago de una reserva ya existente (ej. completar saldo desde Mis reservas)."""
    reserva = obtener_reserva_pagable(usuario, reserva_id)
    monto_cobro = calcular_monto_cobro_reserva(reserva, tipo_pago)
    ctx = creditos_services.contexto_desde_reserva(usuario, reserva)
    monto_tarjeta, descuento, creditos_efectivos = _preparar_cobro_con_creditos(
        usuario, ctx, creditos_usados, monto_cobro, tipo_pago=tipo_pago
    )
    ultimos = _ultimos_4_o_creditos(numero_tarjeta, creditos_efectivos)

    resultado_tarjeta = _validar_tarjeta(
        numero_tarjeta, ultimos, monto_tarjeta, tipo_pago, usuario, reserva=reserva, cvv=cvv
    )
    if not resultado_tarjeta.exito:
        return resultado_tarjeta

    creditos_services.consumir_creditos(
        usuario, reserva.turno.actividad, creditos_efectivos
    )

    referencia = Pago.generar_referencia()
    Pago.objects.create(
        reserva=reserva,
        usuario=usuario,
        monto=monto_tarjeta,
        estado=Pago.Estado.APROBADO,
        tipo_cobro=tipo_pago,
        referencia=referencia,
        ultimos_4=ultimos,
        creditos_usados=creditos_efectivos,
    )

    if tipo_pago == TIPO_SENA:
        _aplicar_pago_aprobado(reserva, tipo_pago, monto_cobro, referencia)
    else:
        _aplicar_pago_aprobado(reserva, tipo_pago, reserva.monto_total, referencia)

    return ResultadoPago(
        exito=True,
        mensaje=_mensaje_exito(
            tipo_pago,
            monto_tarjeta,
            referencia,
            creditos_usados=creditos_efectivos,
            descuento_creditos=descuento,
        ),
        reserva=reserva,
    )


@transaction.atomic
def procesar_pago_grupo(
    usuario,
    grupo_id: int,
    numero_tarjeta: str,
    tipo_pago: str,
    creditos_usados: int = 0,
    *,
    cvv: str = "",
) -> ResultadoPago:
    """Paga o completa el saldo de todas las reservas activas del abono mensual."""
    grupo = obtener_grupo_pagable(usuario, grupo_id)
    monto_cobro = calcular_monto_cobro_grupo(grupo, tipo_pago)
    ctx = creditos_services.contexto_desde_grupo(usuario, grupo)
    monto_tarjeta, descuento, creditos_efectivos = _preparar_cobro_con_creditos(
        usuario, ctx, creditos_usados, monto_cobro, tipo_pago=tipo_pago
    )
    ultimos = _ultimos_4_o_creditos(numero_tarjeta, creditos_efectivos)

    reservas = list(
        grupo.reservas_activas().select_related("turno", "turno__actividad")
    )
    reserva_ref = reservas[0]

    resultado_tarjeta = _validar_tarjeta(
        numero_tarjeta, ultimos, monto_tarjeta, tipo_pago, usuario, reserva=reserva_ref, cvv=cvv
    )
    if not resultado_tarjeta.exito:
        return resultado_tarjeta

    creditos_services.consumir_creditos(
        usuario, grupo.actividad, creditos_efectivos
    )

    referencia = Pago.generar_referencia()
    _aplicar_pago_a_reservas(reservas, tipo_pago, monto_cobro, referencia)

    Pago.objects.create(
        reserva=reserva_ref,
        usuario=usuario,
        monto=monto_tarjeta,
        estado=Pago.Estado.APROBADO,
        tipo_cobro=tipo_pago,
        referencia=referencia,
        ultimos_4=ultimos,
        creditos_usados=creditos_efectivos,
    )

    extra_cred = ""
    if creditos_efectivos:
        extra_cred = " " + _(
            "Se usaron %(n)d crédito(s) ($%(desc)s)."
        ) % {"n": creditos_efectivos, "desc": descuento}

    if tipo_pago == TIPO_SENA:
        mensaje = _(
            "Seña del abono mensual abonada ($%(monto)s). %(n)d turnos. Referencia: %(ref)s"
        ) % {"monto": monto_tarjeta, "n": len(reservas), "ref": referencia} + extra_cred
    elif tipo_pago == TIPO_SALDO:
        mensaje = _(
            "Abono mensual pagado en su totalidad (%(n)d turnos). Referencia: %(ref)s"
        ) % {"n": len(reservas), "ref": referencia} + extra_cred
    else:
        mensaje = _(
            "Abono mensual pagado (%(n)d turnos). Referencia: %(ref)s"
        ) % {"n": len(reservas), "ref": referencia} + extra_cred

    return ResultadoPago(
        exito=True,
        mensaje=mensaje,
        reserva=reserva_ref,
        reservas_creadas=len(reservas),
    )


# ── EMPLOYEE: Registrar Pago en Efectivo (en Sede) ─────────────────────────────

def _validar_reserva_para_pago_efectivo(reserva: Reserva) -> None:
    """
    Valida que una reserva sea apta para registrar pago en efectivo.
    
    Validaciones:
    - Reserva en estado CONFIRMADA o EN_ESPERA (no cancelada)
    - Estado pago NO es PAGADO (no se puede pagar dos veces)
    - Estado pago es PENDIENTE o SEÑADO (solo esos pueden pagarse)
    - Turno NO vencido (fecha >= hoy)
    - Turno existe y es accesible
    
    Lanza ValidationError si alguna validación falla.
    """
    from django.utils import timezone
    
    if reserva.estado == Reserva.Estado.CANCELADA:
        raise ValidationError(
            _("Esta reserva fue cancelada y no puede procesarse.")
        )
    
    if reserva.estado_pago == Reserva.EstadoPago.PAGADO:
        raise ValidationError(
            _("Esta reserva ya está pagada. No se puede registrar otro pago.")
        )
    
    if reserva.estado_pago not in (Reserva.EstadoPago.PENDIENTE, Reserva.EstadoPago.SENADO):
        raise ValidationError(
            _("Esta reserva no está en estado pagable (pendiente o señada).")
        )
    
    if reserva.turno.fecha < timezone.now().date():
        raise ValidationError(
            _("Esta reserva corresponde a un turno vencido (fecha pasada). No se puede procesar el pago.")
        )


def buscar_reservas_por_cliente(criterio: str) -> list[Reserva]:
    """
    Busca reservas que están pendientes de pago para un cliente.
    
    Búsqueda por: nombre, apellido, documento o email del usuario.
    Filtra solo reservas:
    - Estado: CONFIRMADA o EN_ESPERA (no canceladas)
    - Pago: PENDIENTE o SEÑADO (no pagadas)
    - Turno: NO vencido (fecha >= hoy)
    
    Args:
        criterio: Búsqueda libre (nombre, apellido, DNI, email)
    
    Returns:
        Lista de reservas ordenadas por fecha de turno (próximas primero)
        
    Raises:
        ValidationError si criterio está vacío
    """
    from django.utils import timezone
    from django.db.models import Q
    
    criterio = (criterio or "").strip()
    if not criterio:
        raise ValidationError(_("El criterio de búsqueda no puede estar vacío."))
    
    hoy = timezone.now().date()
    
    reservas = Reserva.objects.filter(
        usuario__nombre__icontains=criterio,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
        estado_pago__in=[Reserva.EstadoPago.PENDIENTE, Reserva.EstadoPago.SENADO],
        turno__fecha__gte=hoy,
    ).select_related("usuario", "turno", "turno__actividad")
    
    # O por apellido
    reservas |= Reserva.objects.filter(
        usuario__apellido__icontains=criterio,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
        estado_pago__in=[Reserva.EstadoPago.PENDIENTE, Reserva.EstadoPago.SENADO],
        turno__fecha__gte=hoy,
    ).select_related("usuario", "turno", "turno__actividad")
    
    # O por documento
    reservas |= Reserva.objects.filter(
        usuario__nro_documento__icontains=criterio,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
        estado_pago__in=[Reserva.EstadoPago.PENDIENTE, Reserva.EstadoPago.SENADO],
        turno__fecha__gte=hoy,
    ).select_related("usuario", "turno", "turno__actividad")
    
    # O por email
    reservas |= Reserva.objects.filter(
        usuario__email__icontains=criterio,
        estado__in=[Reserva.Estado.CONFIRMADA, Reserva.Estado.EN_ESPERA],
        estado_pago__in=[Reserva.EstadoPago.PENDIENTE, Reserva.EstadoPago.SENADO],
        turno__fecha__gte=hoy,
    ).select_related("usuario", "turno", "turno__actividad")
    
    return reservas.distinct().order_by("turno__fecha", "turno__hora")


@transaction.atomic
def registrar_pago_efectivo_empleado(
    usuario_empleado,
    reserva_id: int,
    monto_cobrado: Decimal,
) -> ResultadoPago:
    """
    Registra un pago en efectivo en sede (sin tarjeta de crédito).
    
    Solo empleados pueden usar esta función. Actualiza la reserva de SEÑADO/PENDIENTE a PAGADO
    y crea un registro de auditoría en Pago.
    
    Validaciones:
    - Usuario es EMPLOYEE (rol)
    - Reserva existe
    - Reserva NO cancelada
    - Reserva NO ya pagada
    - Reserva en estado PENDIENTE o SEÑADO
    - Turno NO vencido
    - Monto >= monto adeudado
    
    Operación atómica: Si algo falla, no se crear Pago ni se actualiza Reserva.
    Con select_for_update() previene que dos empleados paguen la misma reserva.
    
    Args:
        usuario_empleado: Usuario con rol EMPLOYEE registrando el pago
        reserva_id: ID de la reserva a pagar
        monto_cobrado: Monto en efectivo recibido (Decimal)
    
    Returns:
        ResultadoPago con exito=True si pago se registró correctamente
        
    Raises:
        ValidationError si validación falla
    """
    from apps.accounts.models import Roles
    
    # Validar que usuario es empleado
    if usuario_empleado.rol != Roles.EMPLOYEE:
        raise ValidationError(
            _("Solo empleados pueden registrar pagos en efectivo.")
        )
    
    # Obtener reserva CON LOCK (select_for_update previene race condition)
    try:
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
    except Reserva.DoesNotExist:
        raise ValidationError(_("Reserva no encontrada."))
    
    # Validaciones exhaustivas
    _validar_reserva_para_pago_efectivo(reserva)
    
    # Validar monto
    monto_adeudado = reserva.monto_saldo if reserva.estado_pago == Reserva.EstadoPago.SENADO else reserva.monto_total
    if monto_cobrado < monto_adeudado:
        raise ValidationError(
            _("Monto insuficiente. Se adeuda $%(adeudado)s, se recibió $%(recibido)s.") % {
                "adeudado": monto_adeudado,
                "recibido": monto_cobrado,
            }
        )
    
    # Crear registro de pago (ANTES de actualizar reserva, pero en la misma transacción)
    referencia = Pago.generar_referencia()
    tipo_cobro = TIPO_SALDO if reserva.estado_pago == Reserva.EstadoPago.SENADO else TIPO_TOTAL
    
    pago = Pago.objects.create(
        usuario=usuario_empleado,
        reserva=reserva,
        monto=monto_cobrado,
        estado=Pago.Estado.APROBADO,
        tipo_cobro=tipo_cobro,
        referencia=referencia,
        ultimos_4="EFVT",  # Efectivo
        creditos_usados=0,
    )
    
    # Actualizar estado de reserva (dentro de la misma transacción)
    reserva.estado_pago = Reserva.EstadoPago.PAGADO
    reserva.precio_abonado = reserva.monto_total
    reserva.save(update_fields=["estado_pago", "precio_abonado"])
    
    # Mensaje de éxito
    mensaje = _(
        "✅ Pago en efectivo registrado exitosamente. "
        "Reserva de %(cliente)s (%(actividad)s, %(fecha)s) pasó a estado PAGADO. "
        "Referencia: %(ref)s"
    ) % {
        "cliente": reserva.usuario.get_full_name(),
        "actividad": reserva.turno.actividad.nombre,
        "fecha": reserva.turno.fecha.strftime("%d/%m/%Y"),
        "ref": referencia,
    }
    
    return ResultadoPago(
        exito=True,
        pago=pago,
        mensaje=mensaje,
        reserva=reserva,
    )
