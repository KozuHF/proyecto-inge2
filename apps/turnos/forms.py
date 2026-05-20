from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from .models import DIAS_HABILES, HORAS_VALIDAS
from .services import usuario_puede_reservar_mensual


class PasoActividadForm(forms.Form):
    """Paso 1: El usuario elige la actividad."""

    actividad = forms.ModelChoiceField(
        queryset=Actividad.objects.all(),
        label=_("Actividad"),
        empty_label=_("— Seleccioná una actividad —"),
        widget=forms.RadioSelect,
    )


class PasoFechaForm(forms.Form):
    """Paso 2: El usuario elige la fecha."""

    fecha = forms.DateField(
        label=_("Fecha"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]
        hoy   = timezone.now().date()
        if fecha < hoy:
            raise forms.ValidationError(_("No podés reservar en una fecha pasada."))
        if fecha.weekday() not in DIAS_HABILES:
            raise forms.ValidationError(_("El establecimiento no abre los domingos."))
        return fecha


class PasoHoraForm(forms.Form):
    """Paso 3: El usuario elige la hora."""

    hora = forms.TypedChoiceField(
        label=_("Horario"),
        coerce=int,
        choices=[],   # se inyectan en __init__
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, horas_info=None, **kwargs):
        super().__init__(*args, **kwargs)
        horas_info = horas_info or []
        choices = []
        for info in horas_info:
            hora  = info["hora"]
            label = f"{hora:02d}:00 – {hora + 1:02d}:00"
            if info["lleno"]:
                label += _(" (LLENO – lista de espera: %d)") % info["en_espera"]
            else:
                label += _(" (%d cupos disponibles)") % info["libres"]
            choices.append((hora, label))
        self.fields["hora"].choices = choices


class PasoTipoReservaForm(forms.Form):
    """
    Paso 4: Individual o mensual (solo si la fecha de hoy está en la ventana).

    Si `mensual_disponible` es False, el campo se fuerza a INDIVIDUAL
    y no se muestra la opción mensual.
    """

    TIPO_INDIVIDUAL = "individual"
    TIPO_MENSUAL    = "mensual"

    tipo = forms.ChoiceField(
        label=_("Tipo de reserva"),
        choices=[
            (TIPO_INDIVIDUAL, _("Solo este turno")),
            (TIPO_MENSUAL,    _("Todos los turnos del mes en este día y horario")),
        ],
        widget=forms.RadioSelect,
        initial=TIPO_INDIVIDUAL,
    )

    def __init__(self, *args, mensual_disponible=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not mensual_disponible:
            self.fields["tipo"].choices = [
                (self.TIPO_INDIVIDUAL, _("Solo este turno")),
            ]
            self.fields["tipo"].initial = self.TIPO_INDIVIDUAL
            self.fields["tipo"].help_text = _(
                "La reserva mensual está disponible únicamente entre el 1 y el 10 de cada mes."
            )