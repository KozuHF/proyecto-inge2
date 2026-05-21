import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .forms import TarjetaPagoForm
from . import services

logger = logging.getLogger(__name__)


@login_required
def pagar_reserva(request, reserva_id):
    """Formulario de pago simulado para una reserva del usuario."""
    try:
        reserva = services.obtener_reserva_pagable(request.user, reserva_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("turnos:mis_reservas")

    opciones = services.opciones_pago_reserva(reserva)
    form = TarjetaPagoForm(request.POST or None, opciones_pago=opciones)

    if request.method == "POST" and form.is_valid():
        resultado = services.procesar_pago_reserva(
            request.user,
            reserva_id,
            form.cleaned_data["numero_tarjeta"],
            form.cleaned_data["tipo_pago"],
        )
        if resultado.exito:
            logger.info(
                "Pago aprobado reserva=%s usuario=%s ref=%s tipo=%s",
                reserva_id,
                request.user.pk,
                resultado.pago.referencia,
                resultado.pago.tipo_cobro,
            )
            messages.success(request, resultado.mensaje)
            return redirect("turnos:mis_reservas")

        logger.info(
            "Pago rechazado reserva=%s usuario=%s motivo=%s",
            reserva_id,
            request.user.pk,
            resultado.pago.motivo_rechazo if resultado.pago else "",
        )
        messages.error(request, resultado.mensaje)

    return render(request, "pagos/pagar_reserva.html", {
        "form": form,
        "reserva": reserva,
        "monto_total": reserva.monto_total,
        "monto_sena": reserva.monto_sena,
        "monto_saldo": reserva.monto_saldo,
        "es_senado": reserva.esta_senada,
    })
