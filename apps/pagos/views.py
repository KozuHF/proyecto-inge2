import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.creditos import services as creditos_services
from apps.turnos.views import _wizard_clear, _wizard_get

from .forms import TarjetaPagoForm
from . import services

logger = logging.getLogger(__name__)


def _validar_tarjeta_en_formulario(form, usuario, ctx, creditos_usados, monto_cobro_fn, tipo_pago):
    """Calcula monto con créditos y exige tarjeta solo si queda saldo en efectivo."""
    monto_cobro = monto_cobro_fn(tipo_pago)
    monto_tarjeta, _, _ = services._preparar_cobro_con_creditos(
        usuario, ctx, creditos_usados, monto_cobro, tipo_pago=tipo_pago
    )
    form.validar_tarjeta_si_requerida(monto_tarjeta > 0)
    return monto_tarjeta


@login_required
def pagar_wizard(request):
    """
    Paso 5 del wizard: pago obligatorio antes de crear la reserva.
    Sin pago aprobado no se persiste ningún turno.
    """
    wizard = _wizard_get(request)
    if "modo" not in wizard:
        messages.warning(request, "Completá los pasos de reserva antes de pagar.")
        return redirect("turnos:paso_tipo_abono")

    try:
        datos = services.datos_desde_wizard(wizard)
    except ValidationError as exc:
        messages.error(request, exc.message)
        _wizard_clear(request)
        return redirect("turnos:paso_tipo_abono")

    ctx = creditos_services.contexto_desde_checkout(request.user, datos)
    opciones = services.opciones_pago_nueva_desde_checkout(datos)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form,
            request.user,
            ctx,
            creditos,
            lambda t: services.calcular_monto_cobro_nueva(datos, t),
            tipo,
        )
        if form.errors:
            pass
        else:
            try:
                resultado = services.procesar_pago_y_reservar(
                    request.user,
                    wizard,
                    form.cleaned_data.get("numero_tarjeta") or "",
                    tipo,
                    creditos_usados=creditos,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                _wizard_clear(request)
                logger.info(
                    "Reserva creada tras pago usuario=%s reservas=%s",
                    request.user.pk,
                    resultado.reservas_creadas,
                )
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")

            if resultado and not resultado.exito:
                logger.info(
                    "Pago rechazado en wizard usuario=%s motivo=%s",
                    request.user.pk,
                    resultado.pago.motivo_rechazo if resultado.pago else "",
                )
                messages.error(request, resultado.mensaje)

    from apps.turnos.models import MODO_VARIOS_TURNOS

    return render(request, "pagos/pagar_reserva.html", {
        "form": form,
        "checkout": datos,
        "creditos_ctx": ctx,
        "es_varios": datos.modo == MODO_VARIOS_TURNOS,
        "monto_total": datos.monto_total,
        "monto_sena": services.monto_seña(datos.monto_total),
        "es_checkout": True,
        "paso": 6,
        "modo": datos.modo,
    })


@login_required
def pagar_reserva(request, reserva_id):
    """Pago de una reserva ya existente (completar saldo o reservas antiguas pendientes)."""
    try:
        reserva = services.obtener_reserva_pagable(request.user, reserva_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")

    ctx = creditos_services.contexto_desde_reserva(request.user, reserva)
    opciones = services.opciones_pago_reserva(reserva)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form,
            request.user,
            ctx,
            creditos,
            lambda t: services.calcular_monto_cobro_reserva(reserva, t),
            tipo,
        )
        if not form.errors:
            try:
                resultado = services.procesar_pago_reserva(
                    request.user,
                    reserva_id,
                    form.cleaned_data.get("numero_tarjeta") or "",
                    tipo,
                    creditos_usados=creditos,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                logger.info(
                    "Pago aprobado reserva=%s usuario=%s",
                    reserva_id,
                    request.user.pk,
                )
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")

            if resultado and not resultado.exito:
                messages.error(request, resultado.mensaje)

    return render(request, "pagos/pagar_reserva.html", {
        "form": form,
        "reserva": reserva,
        "creditos_ctx": ctx,
        "monto_total": reserva.monto_total,
        "monto_sena": reserva.monto_sena,
        "monto_saldo": reserva.monto_saldo,
        "es_senado": reserva.esta_senada,
        "es_checkout": False,
    })


@login_required
def pagar_grupo(request, grupo_id):
    """Pago o completar saldo de un abono mensual (todas sus reservas activas)."""
    try:
        grupo = services.obtener_grupo_pagable(request.user, grupo_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")

    ctx = creditos_services.contexto_desde_grupo(request.user, grupo)
    opciones = services.opciones_pago_grupo(grupo)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form,
            request.user,
            ctx,
            creditos,
            lambda t: services.calcular_monto_cobro_grupo(grupo, t),
            tipo,
        )
        if not form.errors:
            try:
                resultado = services.procesar_pago_grupo(
                    request.user,
                    grupo_id,
                    form.cleaned_data.get("numero_tarjeta") or "",
                    tipo,
                    creditos_usados=creditos,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                logger.info(
                    "Pago abono mensual grupo=%s usuario=%s turnos=%s",
                    grupo_id,
                    request.user.pk,
                    resultado.reservas_creadas,
                )
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")

            if resultado and not resultado.exito:
                messages.error(request, resultado.mensaje)

    return render(request, "pagos/pagar_reserva.html", {
        "form": form,
        "grupo": grupo,
        "creditos_ctx": ctx,
        "monto_total": grupo.monto_total_grupo,
        "monto_sena": services.monto_seña(grupo.monto_total_grupo),
        "monto_saldo": grupo.monto_saldo_grupo,
        "es_senado": grupo.esta_senado_grupo,
        "es_checkout": False,
        "es_grupo": True,
    })


@login_required
def cancelar_checkout(request):
    """Abandona el checkout y borra el wizard sin crear reserva."""
    _wizard_clear(request)
    messages.info(request, "Reserva cancelada. No se realizó ningún cargo.")
    return redirect("turnos:paso_tipo_abono")
