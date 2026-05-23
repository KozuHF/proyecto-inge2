from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _

from apps.creditos.services import ContextoPagoCreditos

from . import tarjetas
from .services import TIPO_SENA, normalizar_numero_tarjeta

INPUT_TARJETA = (
    "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
    "focus:ring-green-500 focus:border-green-500 block w-full p-2.5"
)


class TarjetaAltaForm(forms.Form):
    """Alta o reemplazo de tarjeta guardada (registro o Mi cuenta)."""

    numero_tarjeta = forms.CharField(
        label=_("Número de tarjeta"),
        max_length=19,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_TARJETA,
                "placeholder": "0000000000000000",
                "autocomplete": "off",
                "inputmode": "numeric",
            }
        ),
    )
    titular = forms.CharField(
        label=_("Titular"),
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": INPUT_TARJETA, "placeholder": "Nombre Apellido"}
        ),
    )
    vencimiento = forms.CharField(
        label=_("Vencimiento (MM/AA)"),
        max_length=7,
        widget=forms.TextInput(
            attrs={"class": INPUT_TARJETA, "placeholder": "06/29", "autocomplete": "off"}
        ),
    )
    cvv = forms.CharField(
        label=_("CVV"),
        max_length=4,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_TARJETA, "placeholder": "123", "autocomplete": "off"}
        ),
    )

    def clean_numero_tarjeta(self):
        return tarjetas.validar_numero_tarjeta_campo(self.cleaned_data.get("numero_tarjeta", ""))

    def clean_vencimiento(self):
        return tarjetas.validar_vencimiento_campo(self.cleaned_data.get("vencimiento", ""))

    def clean_cvv(self):
        cvv = (self.cleaned_data.get("cvv") or "").strip()
        tarjetas.validar_cvv(cvv)
        return cvv

    def clean_titular(self):
        titular = (self.cleaned_data.get("titular") or "").strip()
        if not titular:
            raise forms.ValidationError(_("Este campo es obligatorio."))
        return titular


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
    modo_tarjeta = forms.ChoiceField(
        label=_("Tarjeta"),
        choices=[
            (tarjetas.MODO_TARJETA_GUARDADA, _("Usar tarjeta guardada")),
            (tarjetas.MODO_TARJETA_NUEVA, _("Cambiar tarjeta")),
        ],
        widget=forms.RadioSelect(
            attrs={"class": "w-4 h-4 text-green-600 border-gray-300 focus:ring-green-500"},
        ),
        required=False,
    )
    numero_tarjeta = forms.CharField(
        label=_("Número de tarjeta"),
        max_length=19,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_TARJETA,
                "placeholder": "0000000000000000",
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
            attrs={"class": INPUT_TARJETA, "placeholder": "Nombre Apellido"}
        ),
    )
    vencimiento = forms.CharField(
        label=_("Vencimiento (MM/AA)"),
        max_length=7,
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_TARJETA, "placeholder": "06/29", "autocomplete": "off"}
        ),
    )
    cvv = forms.CharField(
        label=_("CVV"),
        max_length=4,
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": INPUT_TARJETA, "placeholder": "123", "autocomplete": "off"}
        ),
    )

    def __init__(
        self,
        *args,
        opciones_pago=None,
        creditos_ctx: ContextoPagoCreditos | None = None,
        tarjeta_guardada=None,
        forzar_cambiar_tarjeta: bool = False,
        usuario=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.creditos_ctx = creditos_ctx
        self.tarjeta_guardada = tarjeta_guardada
        self.usuario = usuario
        self.opciones_pago = opciones_pago or []
        self.usar_solo_guardada = bool(tarjeta_guardada) and not forzar_cambiar_tarjeta
        self._requiere_tarjeta = True

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

        if not tarjeta_guardada:
            self.fields["modo_tarjeta"].widget = forms.HiddenInput()
            self.fields["modo_tarjeta"].initial = tarjetas.MODO_TARJETA_NUEVA
            self.usar_solo_guardada = False
        elif forzar_cambiar_tarjeta:
            self.fields["modo_tarjeta"].initial = tarjetas.MODO_TARJETA_NUEVA
            self.usar_solo_guardada = False
        else:
            self.fields["modo_tarjeta"].initial = tarjetas.MODO_TARJETA_GUARDADA

    @property
    def modo_guardada(self) -> bool:
        if not self.tarjeta_guardada:
            return False
        if self.is_bound:
            return self.data.get("modo_tarjeta") == tarjetas.MODO_TARJETA_GUARDADA
        return self.usar_solo_guardada

    @property
    def requiere_tarjeta(self) -> bool:
        return self._requiere_tarjeta

    def monto_cobro_para_tipo(self, tipo_pago: str | None) -> Decimal:
        for valor, _, monto in self.opciones_pago:
            if valor == tipo_pago:
                return Decimal(monto)
        return Decimal("0")

    def monto_tarjeta_tras_creditos(self, cleaned: dict) -> Decimal:
        from . import services

        tipo = cleaned.get("tipo_pago")
        creditos = cleaned.get("creditos_usados") or 0
        monto_cobro = self.monto_cobro_para_tipo(tipo)
        try:
            monto_tarjeta, _, _ = services._preparar_cobro_con_creditos(
                self.usuario,
                self.creditos_ctx,
                creditos,
                monto_cobro,
                tipo_pago=tipo,
            )
        except DjangoValidationError as exc:
            self.add_error("creditos_usados", exc.messages)
            return monto_cobro
        return monto_tarjeta

    def clean(self):
        cleaned = super().clean()
        creditos = cleaned.get("creditos_usados") or 0
        if creditos > 0 and cleaned.get("tipo_pago") == TIPO_SENA:
            self.add_error(
                "tipo_pago",
                _("No podés pagar seña si usás créditos. Elegí pago total."),
            )

        self._requiere_tarjeta = self.monto_tarjeta_tras_creditos(cleaned) > 0
        if not self._requiere_tarjeta:
            return cleaned

        modo = cleaned.get("modo_tarjeta") or tarjetas.MODO_TARJETA_NUEVA
        if not self.tarjeta_guardada:
            modo = tarjetas.MODO_TARJETA_NUEVA

        cvv = (cleaned.get("cvv") or "").strip()
        if not cvv:
            self.add_error("cvv", _("Este campo es obligatorio."))
        else:
            try:
                tarjetas.validar_cvv(cvv)
            except DjangoValidationError as exc:
                self.add_error("cvv", exc.messages)

        if modo == tarjetas.MODO_TARJETA_GUARDADA:
            if not self.tarjeta_guardada:
                self.add_error("modo_tarjeta", _("No tenés tarjeta guardada."))
            return cleaned

        numero = cleaned.get("numero_tarjeta", "")
        titular = (cleaned.get("titular") or "").strip()
        vencimiento = cleaned.get("vencimiento", "")

        if not numero:
            self.add_error("numero_tarjeta", _("Este campo es obligatorio."))
        else:
            try:
                tarjetas.validar_numero_tarjeta_campo(numero)
            except forms.ValidationError as exc:
                self.add_error("numero_tarjeta", exc.messages)

        if not titular:
            self.add_error("titular", _("Este campo es obligatorio."))
        if not vencimiento:
            self.add_error("vencimiento", _("Este campo es obligatorio."))
        else:
            try:
                cleaned["vencimiento"] = tarjetas.validar_vencimiento_campo(vencimiento)
            except forms.ValidationError as exc:
                self.add_error("vencimiento", exc.messages)

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

    def validar_tarjeta_si_requerida(self, requiere_tarjeta: bool):
        if not requiere_tarjeta:
            self._requiere_tarjeta = False

    def datos_tarjeta_para_pago(self, usuario):
        """Devuelve (pan, cvv, reemplazar_guardada)."""
        if not self.requiere_tarjeta:
            return "", "", False
        cvv = self.cleaned_data.get("cvv") or ""
        modo = self.cleaned_data.get("modo_tarjeta") or tarjetas.MODO_TARJETA_NUEVA
        if self.tarjeta_guardada and modo == tarjetas.MODO_TARJETA_GUARDADA:
            pan = tarjetas.resolver_pan_pago(usuario, True, "")
            return pan, cvv, False
        pan = normalizar_numero_tarjeta(self.cleaned_data["numero_tarjeta"])
        return pan, cvv, True
