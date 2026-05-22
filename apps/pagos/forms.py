import calendar
import re
from datetime import date

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .services import normalizar_numero_tarjeta


def _ultimo_dia_del_mes(anio: int, mes: int) -> date:
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, ultimo)


def parsear_vencimiento(valor: str) -> tuple[int, int]:
    """
    Interpreta MM/AA o MM/AAAA (también acepta guión en lugar de barra).
    Devuelve (mes, año_completo).
    """
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


class TarjetaPagoForm(forms.Form):
    tipo_pago = forms.ChoiceField(
        label=_("Forma de pago"),
        widget=forms.RadioSelect(
            attrs={"class": "w-4 h-4 text-green-600 border-gray-300 focus:ring-green-500"},
        ),
    )

    numero_tarjeta = forms.CharField(
        label=_("Número de tarjeta"),
        max_length=19,
        widget=forms.TextInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-full p-2.5",
                "placeholder": "0000 0000 0000 0000",
                "autocomplete": "off",
                "inputmode": "numeric",
            }
        ),
    )
    titular = forms.CharField(
        label=_("Titular"),
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-full p-2.5",
                "placeholder": "Nombre Apellido",
            }
        ),
    )
    vencimiento = forms.CharField(
        label=_("Vencimiento (MM/AA)"),
        max_length=7,
        widget=forms.TextInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-full p-2.5",
                "placeholder": "06/29",
                "autocomplete": "off",
            }
        ),
    )
    cvv = forms.CharField(
        label=_("CVV"),
        max_length=4,
        widget=forms.PasswordInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-full p-2.5",
                "placeholder": "123",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, opciones_pago=None, **kwargs):
        super().__init__(*args, **kwargs)
        if opciones_pago is not None:
            self.fields["tipo_pago"].choices = [
                (valor, f"{etiqueta} — ${monto}") for valor, etiqueta, monto in opciones_pago
            ]
            if len(opciones_pago) == 1:
                self.fields["tipo_pago"].initial = opciones_pago[0][0]

    def clean_numero_tarjeta(self):
        numero = self.cleaned_data["numero_tarjeta"]
        pan = normalizar_numero_tarjeta(numero)
        if len(pan) != 16 or not pan.isdigit():
            raise forms.ValidationError(_("Ingresá los 16 dígitos de la tarjeta."))
        return numero

    def clean_vencimiento(self):
        valor = self.cleaned_data["vencimiento"].strip()
        try:
            mes, anio = parsear_vencimiento(valor)
        except ValueError:
            raise forms.ValidationError(_("Formato inválido. Usá MM/AA (ej: 06/29)."))

        hoy = timezone.localdate()
        vence_el = _ultimo_dia_del_mes(anio, mes)

        if vence_el < hoy:
            raise forms.ValidationError(_("La tarjeta está vencida."))

        if anio > hoy.year + 15:
            raise forms.ValidationError(_("La fecha de vencimiento no es válida."))

        return f"{mes:02d}/{anio % 100:02d}"

    def clean_cvv(self):
        cvv = self.cleaned_data["cvv"].strip()
        if not cvv.isdigit() or len(cvv) not in (3, 4):
            raise forms.ValidationError(_("CVV inválido."))
        return cvv
