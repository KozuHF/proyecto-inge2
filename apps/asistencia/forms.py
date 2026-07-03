"""
Formularios de la app asistencia.
"""
from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import validar_dni


class BuscarPorDniForm(forms.Form):
    """Búsqueda de un cliente por DNI para el marcado manual de asistencia."""

    nro_documento = forms.CharField(
        label=_("DNI del cliente"),
        max_length=8,
        validators=[validar_dni],
        widget=forms.TextInput(attrs={
            "placeholder": "12345678",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "maxlength": "8",
            "autofocus": "autofocus",
            "onkeypress": "return /[0-9]/.test(event.key)",
            "oninput": "this.value = this.value.replace(/\\D/g, '').slice(0, 8)",
            "class": (
                "w-full rounded-lg border border-gray-300 dark:border-gray-600 "
                "dark:bg-gray-700 dark:text-white px-4 py-3 text-sm "
                "focus:ring-2 focus:ring-green-500 focus:border-green-500"
            ),
        }),
    )

    def clean_nro_documento(self):
        return self.cleaned_data["nro_documento"].strip()
