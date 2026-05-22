from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from .models import DIAS_HABILES, HORAS_VALIDAS, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS


class PasoTipoAbonoForm(forms.Form):
    """Paso 1: Turno único o varios turnos del mes."""

    modo = forms.ChoiceField(
        label=_("Tipo de abono"),
        choices=[
            (MODO_TURNO_UNICO, _("Turno único")),
            (MODO_VARIOS_TURNOS, _("Abonado mensual")),
        ],
        widget=forms.RadioSelect,
        initial=MODO_TURNO_UNICO,
    )


class PasoActividadForm(forms.Form):
    """Paso 2: El usuario elige la actividad."""

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


class PasoSeleccionFechasForm(forms.Form):
    """Paso 5 (varios turnos): elegir qué días del mes reservar."""

    fechas = forms.MultipleChoiceField(
        label=_("Días a reservar"),
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Seleccioná al menos un día.")},
    )

    def __init__(self, *args, fechas_candidatas=None, **kwargs):
        super().__init__(*args, **kwargs)
        fechas_candidatas = fechas_candidatas or []
        nombres = [_("Lunes"), _("Martes"), _("Miércoles"), _("Jueves"), _("Viernes"), _("Sábado")]
        self.fields["fechas"].choices = [
            (
                f.isoformat(),
                f"{nombres[f.weekday()]} {f.day:02d}/{f.month:02d}/{f.year}",
            )
            for f in fechas_candidatas
        ]