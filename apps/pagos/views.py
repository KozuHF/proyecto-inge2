import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.creditos import services as creditos_services
from apps.turnos.views import _wizard_clear, _wizard_get

from . import tarjetas
from .forms import TarjetaPagoForm
from . import services

logger = logging.getLogger(__name__)


def _tarjeta_contexto(request):
    tarjeta = tarjetas.obtener_tarjeta_guardada(request.user)
    forzar_cambiar = request.GET.get("cambiar") == "1"
    return tarjeta, forzar_cambiar


def _validar_tarjeta_en_formulario(form, usuario, ctx, creditos_usados, monto_cobro_fn, tipo_pago):
    monto_cobro = monto_cobro_fn(tipo_pago)
    monto_tarjeta, _, _ = services._preparar_cobro_con_creditos(
        usuario, ctx, creditos_usados, monto_cobro, tipo_pago=tipo_pago
    )
    form.validar_tarjeta_si_requerida(monto_tarjeta > 0)
    return monto_tarjeta


def _preparar_tarjeta_tras_pago(request, form):
    if not form.requiere_tarjeta:
        return "", ""
    pan, cvv, reemplazar = form.datos_tarjeta_para_pago(request.user)
    if reemplazar:
        tarjetas.guardar_tarjeta(
            request.user,
            form.cleaned_data["numero_tarjeta"],
            form.cleaned_data["titular"],
            form.cleaned_data["vencimiento"],
        )
    return pan, cvv


def _ctx_montos_pago(opciones, creditos_ctx):
    montos = {valor: str(monto) for valor, _, monto in (opciones or [])}
    valor = "0"
    if creditos_ctx:
        valor = str(creditos_ctx.valor_credito)
    return {
        "montos_pago": montos,
        "valor_credito_pago": valor,
    }


def _render_pago(request, template_ctx):
    template_ctx.setdefault("tarjeta_guardada", None)
    template_ctx.setdefault("forzar_cambiar_tarjeta", False)
    template_ctx.setdefault("montos_pago", {})
    template_ctx.setdefault("valor_credito_pago", "0")
    return render(request, "pagos/pagar_reserva.html", template_ctx)


@login_required
def pagar_wizard(request):
    wizard = _wizard_get(request)
    if "modo" not in wizard:
        messages.warning(request, "Completá los pasos de reserva antes de pagar.")
        return redirect("turnos:paso_tipo_abono")

    try:
        datos = services.datos_desde_wizard(wizard, request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
        _wizard_clear(request)
        return redirect("turnos:paso_tipo_abono")

    tarjeta_guardada, forzar_cambiar = _tarjeta_contexto(request)
    ctx = creditos_services.contexto_desde_checkout(request.user, datos)
    opciones = services.opciones_pago_nueva_desde_checkout(datos)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
        tarjeta_guardada=tarjeta_guardada,
        forzar_cambiar_tarjeta=forzar_cambiar,
        usuario=request.user,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form, request.user, ctx, creditos,
            lambda t: services.calcular_monto_cobro_nueva(datos, t), tipo,
        )
        if not form.errors:
            try:
                pan, cvv = _preparar_tarjeta_tras_pago(request, form)
                resultado = services.procesar_pago_y_reservar(
                    request.user, wizard, pan, tipo,
                    creditos_usados=creditos, cvv=cvv,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                _wizard_clear(request)
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")
            if resultado and not resultado.exito:
                messages.error(request, resultado.mensaje)

    from apps.turnos.abono_mensual import REGLA_SEGUNDA_QUINCENA
    from apps.turnos.models import MODO_VARIOS_TURNOS
    from apps.turnos.penalidad_cancelaciones import mensaje_sin_beneficio_segunda_quincena

    aviso_sin_beneficio = None
    if datos.modo == MODO_VARIOS_TURNOS and datos.regla_cobro == REGLA_SEGUNDA_QUINCENA:
        aviso_sin_beneficio = mensaje_sin_beneficio_segunda_quincena(
            request.user, datos.fecha.year, datos.fecha.month
        )

    return _render_pago(request, {
        "form": form,
        "checkout": datos,
        "creditos_ctx": ctx,
        "tarjeta_guardada": tarjeta_guardada,
        "forzar_cambiar_tarjeta": forzar_cambiar,
        "es_varios": datos.modo == MODO_VARIOS_TURNOS,
        "monto_total": datos.monto_total,
        "monto_sena": services.monto_seña(datos.monto_total),
        "es_checkout": True,
        "paso": 6,
        "modo": datos.modo,
        "aviso_sin_beneficio": aviso_sin_beneficio,
        **_ctx_montos_pago(opciones, ctx),
    })


@login_required
def pagar_reserva(request, reserva_id):
    try:
        reserva = services.obtener_reserva_pagable(request.user, reserva_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")

    tarjeta_guardada, forzar_cambiar = _tarjeta_contexto(request)
    ctx = creditos_services.contexto_desde_reserva(request.user, reserva)
    opciones = services.opciones_pago_reserva(reserva)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
        tarjeta_guardada=tarjeta_guardada,
        forzar_cambiar_tarjeta=forzar_cambiar,
        usuario=request.user,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form, request.user, ctx, creditos,
            lambda t: services.calcular_monto_cobro_reserva(reserva, t), tipo,
        )
        if not form.errors:
            try:
                pan, cvv = _preparar_tarjeta_tras_pago(request, form)
                resultado = services.procesar_pago_reserva(
                    request.user, reserva_id, pan, tipo,
                    creditos_usados=creditos, cvv=cvv,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")
            if resultado and not resultado.exito:
                messages.error(request, resultado.mensaje)

    return _render_pago(request, {
        "form": form,
        "reserva": reserva,
        "creditos_ctx": ctx,
        "tarjeta_guardada": tarjeta_guardada,
        "forzar_cambiar_tarjeta": forzar_cambiar,
        "monto_total": reserva.monto_total,
        "monto_sena": reserva.monto_sena,
        "monto_saldo": reserva.monto_saldo,
        "es_senado": reserva.esta_senada,
        "es_checkout": False,
        **_ctx_montos_pago(opciones, ctx),
    })


@login_required
def pagar_grupo(request, grupo_id):
    try:
        grupo = services.obtener_grupo_pagable(request.user, grupo_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")

    tarjeta_guardada, forzar_cambiar = _tarjeta_contexto(request)
    ctx = creditos_services.contexto_desde_grupo(request.user, grupo)
    opciones = services.opciones_pago_grupo(grupo)
    form = TarjetaPagoForm(
        request.POST or None,
        opciones_pago=opciones,
        creditos_ctx=ctx,
        tarjeta_guardada=tarjeta_guardada,
        forzar_cambiar_tarjeta=forzar_cambiar,
        usuario=request.user,
    )

    if request.method == "POST" and form.is_valid():
        creditos = form.cleaned_data["creditos_usados"] or 0
        tipo = form.cleaned_data["tipo_pago"]
        _validar_tarjeta_en_formulario(
            form, request.user, ctx, creditos,
            lambda t: services.calcular_monto_cobro_grupo(grupo, t), tipo,
        )
        if not form.errors:
            try:
                pan, cvv = _preparar_tarjeta_tras_pago(request, form)
                resultado = services.procesar_pago_grupo(
                    request.user, grupo_id, pan, tipo,
                    creditos_usados=creditos, cvv=cvv,
                )
            except ValidationError as exc:
                messages.error(request, exc.message)
                resultado = None

            if resultado and resultado.exito:
                messages.success(request, resultado.mensaje)
                return redirect("turnos:mis_reservas")
            if resultado and not resultado.exito:
                messages.error(request, resultado.mensaje)

    from apps.turnos.abono_mensual import REGLA_SEGUNDA_QUINCENA
    from apps.turnos.penalidad_cancelaciones import mensaje_sin_beneficio_segunda_quincena

    aviso_sin_beneficio = None
    if grupo.regla_cobro == REGLA_SEGUNDA_QUINCENA:
        aviso_sin_beneficio = mensaje_sin_beneficio_segunda_quincena(
            request.user, grupo.anio, grupo.mes
        )

    return _render_pago(request, {
        "form": form,
        "grupo": grupo,
        "creditos_ctx": ctx,
        "tarjeta_guardada": tarjeta_guardada,
        "forzar_cambiar_tarjeta": forzar_cambiar,
        "monto_total": grupo.monto_total_grupo,
        "monto_sena": services.monto_seña(grupo.monto_total_grupo),
        "monto_saldo": grupo.monto_saldo_grupo,
        "es_senado": grupo.esta_senado_grupo,
        "es_checkout": False,
        "es_grupo": True,
        "aviso_sin_beneficio": aviso_sin_beneficio,
        **_ctx_montos_pago(opciones, ctx),
    })


@login_required
def cancelar_checkout(request):
    _wizard_clear(request)
    messages.info(request, "Reserva cancelada. No se realizó ningún cargo.")
    return redirect("turnos:paso_tipo_abono")
