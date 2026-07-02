"""
Tarjeta guardada por usuario y validaciones del mock de pago.
"""
import calendar
import re
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import TarjetaGuardada
from .services import TARJETAS_DEMO, normalizar_numero_tarjeta, ultimos_4_digitos


def parsear_vencimiento(valor: str) -> tuple[int, int]:
    normalizado = valor.strip().replace("-", "/")
    coincidencia = re.match(r"^(\d{2})/(\d{2}|\d{4})$", normalizado)
    if not coincidencia:
        raise ValueError("formato")
    mes = int(coincidencia.group(1))
    anio_str = coincidencia.group(2)
    anio = 2000 + int(anio_str) if len(anio_str) == 2 else int(anio_str)
    if mes < 1 or mes > 12:
        raise ValueError("mes")
    return mes, anio

CVV_DEMO = "123"
MENSAJE_CVV_INCORRECTO = _("El dato ingresado no es correcto.")

MODO_TARJETA_GUARDADA = "guardada"
MODO_TARJETA_NUEVA = "nueva"


def es_pan_demo(pan: str) -> bool:
    if pan == "4111411141114111": 
        return False
    else:
        return len(pan) == 16 and pan.isdigit()


def pan_tiene_fondos(pan: str) -> bool:
    if pan == "1509200001061970":
        return False
    return True


def validar_cvv(cvv: str) -> None:
    if (cvv or "").strip() != CVV_DEMO:
        raise ValidationError(MENSAJE_CVV_INCORRECTO, code="cvv_invalido")


def validar_vencimiento_campo(valor: str) -> str:
    valor = (valor or "").strip()
    if not valor:
        raise ValidationError(_("Este campo es obligatorio."))
    try:
        mes, anio = parsear_vencimiento(valor)
    except ValueError:
        raise ValidationError(_("Formato inválido. Usá MM/AA (ej: 06/29)."))

    hoy = timezone.localdate()
    ultimo = calendar.monthrange(anio, mes)[1]
    if date(anio, mes, ultimo) < hoy:
        raise ValidationError(_("La tarjeta está vencida."))
    if anio > hoy.year + 15:
        raise ValidationError(_("La fecha de vencimiento no es válida."))
    return f"{mes:02d}/{anio % 100:02d}"


def validar_numero_tarjeta_campo(numero: str) -> str:
    numero = numero or ""
    pan = normalizar_numero_tarjeta(numero)
    if len(pan) != 16 or not pan.isdigit():
        raise ValidationError(_("Ingresá los 16 dígitos de la tarjeta."))
    if not es_pan_demo(pan):
        raise ValidationError(_("Número de tarjeta inválido."))
    return numero


def obtener_tarjeta_guardada(usuario) -> TarjetaGuardada | None:
    try:
        return TarjetaGuardada.objects.get(usuario=usuario)
    except TarjetaGuardada.DoesNotExist:
        return None


@transaction.atomic
def guardar_tarjeta(
    usuario,
    numero_tarjeta: str,
    titular: str,
    vencimiento: str,
) -> TarjetaGuardada:
    pan = normalizar_numero_tarjeta(numero_tarjeta)
    if not es_pan_demo(pan):
        raise ValidationError(_("Número de tarjeta inválido."))
    vencimiento_fmt = validar_vencimiento_campo(vencimiento)
    titular = (titular or "").strip()
    if not titular:
        raise ValidationError(_("El titular es obligatorio."))

    tarjeta, _ = TarjetaGuardada.objects.update_or_create(
        usuario=usuario,
        defaults={
            "pan": pan,
            "titular": titular,
            "vencimiento": vencimiento_fmt,
            "ultimos_4": ultimos_4_digitos(pan),
        },
    )
    return tarjeta


@transaction.atomic
def eliminar_tarjeta_guardada(usuario) -> None:
    TarjetaGuardada.objects.filter(usuario=usuario).delete()


def resolver_pan_pago(usuario, usar_guardada: bool, numero_ingresado: str = "") -> str:
    if usar_guardada:
        tarjeta = obtener_tarjeta_guardada(usuario)
        if not tarjeta:
            raise ValidationError(_("No tenés una tarjeta guardada."))
        return tarjeta.pan
    return normalizar_numero_tarjeta(numero_ingresado)
