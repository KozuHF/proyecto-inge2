from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.actividades.models import Actividad
from .models import DIAS_HABILES, HORAS_VALIDAS, MODO_TURNO_UNICO, MODO_VARIOS_TURNOS, FERIADOS_INAMOVIBLES


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
        if (fecha.month, fecha.day) in FERIADOS_INAMOVIBLES:
            raise forms.ValidationError(_("El establecimiento permanece cerrado por feriado nacional."))
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


from .models import Turno
from apps.accounts.forms import PANEL_INPUT_CLASS


class TurnoForm(forms.ModelForm):
    modificar_futuros = forms.BooleanField(
        required=False,
        label=_("Aplicar cambios a turnos futuros"),
        help_text=_("Si se marca, se actualizarán o crearán todos los turnos futuros del mismo horario y día de la semana."),
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "w-4 h-4 text-green-600 bg-gray-50 border-gray-300 rounded "
                    "focus:ring-green-500 focus:ring-2 dark:bg-gray-700 dark:border-gray-600"
                )
            }
        )
    )

    class Meta:
        model = Turno
        fields = ["fecha", "actividad", "hora", "cupos", "precio_override"]
        widgets = {
            "actividad": forms.Select(attrs={"class": PANEL_INPUT_CLASS}),
            "fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": PANEL_INPUT_CLASS}),
            "hora": forms.NumberInput(attrs={"class": PANEL_INPUT_CLASS, "min": 8, "max": 21}),
            "cupos": forms.NumberInput(attrs={"class": PANEL_INPUT_CLASS, "min": 1}),
            "precio_override": forms.NumberInput(attrs={"class": PANEL_INPUT_CLASS, "min": 0, "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha"].disabled = True
        self.fields["fecha"].required = False
        self.fields["actividad"].disabled = True
        self.fields["actividad"].required = False
        self.fields["precio_override"].label = _("Precio")
        if self.instance and self.instance.actividad_id:
            precio_base = self.instance.actividad.precio_turno
            self.fields["precio_override"].help_text = _(
                "Dejar vacío para mantener el precio actual ($%(precio)s)."
            ) % {"precio": precio_base}