import calendar
import re
from datetime import date

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.creditos.services import ContextoPagoCreditos

from .services import TIPO_SENA, normalizar_numero_tarjeta


def _ultimo_dia_del_mes(anio: int, mes: int) -> date:
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, ultimo)


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


class TarjetaPagoForm(forms.Form):
    tipo_pago = forms.ChoiceField(
        label=_("Forma de pago"),
        widget=forms.RadioSelect(
            attrs={"class": "w-4 h-4 text-green-600 border-gray-300 focus:ring-green-500"},
        ),
    )
    creditos_usados = forms.IntegerField(
        label=_("Créditos a utilizar"),
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-24 p-2.5",
                "min": "0",
            }
        ),
    )
    numero_tarjeta = forms.CharField(
        label=_("Número de tarjeta"),
        max_length=19,
        required=False,
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
        required=False,
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
        required=False,
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
        required=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
                         "focus:ring-green-500 focus:border-green-500 block w-full p-2.5",
                "placeholder": "123",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(
        self,
        *args,
        opciones_pago=None,
        creditos_ctx: ContextoPagoCreditos | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.creditos_ctx = creditos_ctx

        if opciones_pago is not None:
            self.fields["tipo_pago"].choices = [
                (valor, f"{etiqueta} — ${monto}") for valor, etiqueta, monto in opciones_pago
            ]
            if len(opciones_pago) == 1:
                self.fields["tipo_pago"].initial = opciones_pago[0][0]

        if not creditos_ctx or creditos_ctx.saldo <= 0 or creditos_ctx.max_creditos <= 0:
            self.fields["creditos_usados"].widget = forms.HiddenInput()
            self.fields["creditos_usados"].initial = 0
        else:
            self.fields["creditos_usados"].widget.attrs["max"] = str(creditos_ctx.max_creditos)

    def clean(self):
        cleaned = super().clean()
        creditos = cleaned.get("creditos_usados") or 0
        if creditos > 0 and cleaned.get("tipo_pago") == TIPO_SENA:
            self.add_error(
                "tipo_pago",
                _("No podés pagar seña si usás créditos. Elegí pago total."),
            )
        return cleaned

    def clean_creditos_usados(self):
        valor = self.cleaned_data.get("creditos_usados")
        if valor is None:
            return 0
        if self.creditos_ctx:
            if valor > self.creditos_ctx.saldo:
                raise forms.ValidationError(
                    _("Tenés %(n)d crédito(s) disponible(s) de este deporte.")
                    % {"n": self.creditos_ctx.saldo}
                )
            if valor > self.creditos_ctx.max_creditos:
                raise forms.ValidationError(
                    _("Podés usar como máximo %(n)d crédito(s) en este pago.")
                    % {"n": self.creditos_ctx.max_creditos}
                )
        return valor

    def clean_numero_tarjeta(self):
        numero = self.cleaned_data.get("numero_tarjeta", "")
        if not numero:
            return numero
        pan = normalizar_numero_tarjeta(numero)
        if len(pan) != 16 or not pan.isdigit():
            raise forms.ValidationError(_("Ingresá los 16 dígitos de la tarjeta."))
        return numero

    def clean_vencimiento(self):
        valor = (self.cleaned_data.get("vencimiento") or "").strip()
        if not valor:
            return valor
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
        cvv = (self.cleaned_data.get("cvv") or "").strip()
        if not cvv:
            return cvv
        if not cvv.isdigit() or len(cvv) not in (3, 4):
            raise forms.ValidationError(_("CVV inválido."))
        return cvv

    def validar_tarjeta_si_requerida(self, requiere_tarjeta: bool):
        if not requiere_tarjeta:
            return
        for nombre in ("numero_tarjeta", "titular", "vencimiento", "cvv"):
            if not self.cleaned_data.get(nombre):
                self.add_error(nombre, _("Este campo es obligatorio."))
