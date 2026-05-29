from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

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

    def __init__(self, *args, horas_info=None, usuario=None, fecha=None, **kwargs):
        super().__init__(*args, **kwargs)
        horas_info = horas_info or []
        
        # Busquemos las horas en las que el usuario ya tiene reserva ese día
        horas_ocupadas = set()
        if usuario and fecha:
            from .models import Reserva
            reservas_usuario = Reserva.objects.filter(
                usuario=usuario,
                turno__fecha=fecha
            ).exclude(estado=Reserva.Estado.CANCELADA)
            horas_ocupadas = set(reservas_usuario.values_list("turno__hora", flat=True))

        choices = []
        for info in horas_info:
            hora  = info["hora"]
            label = f"{hora:02d}:00 – {hora + 1:02d}:00"
            if hora in horas_ocupadas:
                label += _(" (Ya tenés una reserva a esta hora)")
            elif info["lleno"]:
                label += _(" (LLENO – lista de espera: %d)") % info["en_espera"]
            else:
                label += _(" (%d cupos disponibles)") % info["libres"]
            choices.append((hora, label))
        
        self.fields["hora"].choices = choices
        self.horas_ocupadas = {str(h) for h in horas_ocupadas}

    def clean_hora(self):
        hora = self.cleaned_data.get("hora")
        if hora is not None and str(hora) in self.horas_ocupadas:
            raise forms.ValidationError(_("No podés seleccionar un horario en el que ya tenés otra reserva."))
        return hora


class PasoSeleccionFechasForm(forms.Form):
    """Paso 5 (varios turnos): elegir qué días del mes reservar."""

    fechas = forms.MultipleChoiceField(
        label=_("Días a reservar"),
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Seleccioná al menos un día.")},
    )

    def __init__(self, *args, fechas_candidatas=None, usuario=None, hora=None, **kwargs):
        super().__init__(*args, **kwargs)
        fechas_candidatas = fechas_candidatas or []
        nombres = [_("Lunes"), _("Martes"), _("Miércoles"), _("Jueves"), _("Viernes"), _("Sábado")]
        
        # Busquemos las fechas en las que el usuario ya tiene reserva a esa hora
        fechas_ocupadas = set()
        if usuario and hora is not None:
            from .models import Reserva
            reservas_usuario = Reserva.objects.filter(
                usuario=usuario,
                turno__hora=hora,
                turno__fecha__in=fechas_candidatas
            ).exclude(estado=Reserva.Estado.CANCELADA)
            fechas_ocupadas = set(reservas_usuario.values_list("turno__fecha", flat=True))

        self.fields["fechas"].choices = [
            (
                f.isoformat(),
                f"{nombres[f.weekday()]} {f.day:02d}/{f.month:02d}/{f.year}" +
                (_(" (Ya tenés una reserva a esta hora)") if f in fechas_ocupadas else ""),
            )
            for f in fechas_candidatas
        ]
        self.fechas_ocupadas = {f.isoformat() for f in fechas_ocupadas}

    def clean_fechas(self):
        fechas = self.cleaned_data.get("fechas")
        for f_str in fechas:
            if f_str in self.fechas_ocupadas:
                raise forms.ValidationError(_("No podés seleccionar un día en el que ya tenés otra reserva a la misma hora."))
        return fechas


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
            "hora": forms.Select(
                choices=[(h, f"{h:02d}:00 – {h + 1:02d}:00") for h in HORAS_VALIDAS],
                attrs={"class": PANEL_INPUT_CLASS},
            ),
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

        # Filter out occupied hours for this activity and date (excluding current instance hour)
        if self.instance and self.instance.actividad_id and self.instance.fecha:
            horas_ocupadas_qs = Turno.objects.filter(
                actividad=self.instance.actividad,
                fecha=self.instance.fecha
            )
            if self.instance.pk:
                horas_ocupadas_qs = horas_ocupadas_qs.exclude(pk=self.instance.pk)
            
            horas_ocupadas = set(horas_ocupadas_qs.values_list("hora", flat=True))
            
            self.fields["hora"].choices = [
                (h, f"{h:02d}:00 – {h + 1:02d}:00")
                for h in HORAS_VALIDAS
                if h not in horas_ocupadas
            ]


from .models import HorarioDisponible, DIAS_SEMANA_CHOICES, HORAS_VALIDAS


class HorarioDisponibleForm(forms.ModelForm):
    """
    Formulario para que el admin cree o edite un HorarioDisponible.

    Selecciona la actividad, el día de la semana y la hora de inicio.
    El sistema valida automáticamente que no haya solapamiento.
    """

    class Meta:
        model = HorarioDisponible
        fields = ["actividad", "dia_semana", "hora", "cupos", "precio", "activo"]
        widgets = {
            "actividad": forms.Select(attrs={"class": PANEL_INPUT_CLASS}),
            "dia_semana": forms.Select(
                choices=DIAS_SEMANA_CHOICES,
                attrs={"class": PANEL_INPUT_CLASS},
            ),
            "hora": forms.Select(
                choices=[(h, f"{h:02d}:00 – {h + 1:02d}:00") for h in HORAS_VALIDAS],
                attrs={"class": PANEL_INPUT_CLASS},
            ),
            "cupos": forms.NumberInput(attrs={"class": PANEL_INPUT_CLASS, "min": 1}),
            "precio": forms.NumberInput(attrs={"class": PANEL_INPUT_CLASS, "min": 0.01, "step": "0.01"}),
        }

    def clean(self):
        # El clean estándar de ModelForm, la validación de unicidad se maneja en validate_unique
        return super().clean()

    def validate_unique(self):
        try:
            self.instance.validate_unique()
        except ValidationError as e:
            actividad = self.cleaned_data.get("actividad")
            dia_semana = self.cleaned_data.get("dia_semana")
            hora = self.cleaned_data.get("hora")
            activo = self.cleaned_data.get("activo", True)

            if actividad and dia_semana is not None and hora is not None and activo:
                django_week_day = (dia_semana + 1) % 7 + 1
                tiene_turnos_futuros = Turno.objects.filter(
                    actividad=actividad,
                    hora=hora,
                    fecha__gte=timezone.now().date(),
                    fecha__week_day=django_week_day
                ).exists()

                if not tiene_turnos_futuros:
                    # No tiene turnos futuros, así que podemos ignorar el error de unicidad.
                    non_unique_errors = {}
                    for field, errors in e.error_dict.items():
                        filtered_errors = []
                        for error in errors:
                            if error.code == 'unique_together':
                                continue
                            filtered_errors.append(error)
                        if filtered_errors:
                            non_unique_errors[field] = filtered_errors
                    
                    if non_unique_errors:
                        self._update_errors(ValidationError(non_unique_errors))
                    return
                else:
                    # Sí tiene turnos futuros, mostramos un error amigable en vez del de Django
                    non_unique_errors = {}
                    has_ut = False
                    for field, errors in e.error_dict.items():
                        filtered_errors = []
                        for error in errors:
                            if error.code == 'unique_together':
                                has_ut = True
                                continue
                            filtered_errors.append(error)
                        if filtered_errors:
                            non_unique_errors[field] = filtered_errors
                    
                    if has_ut:
                        dia_nombre = dict(DIAS_SEMANA_CHOICES).get(dia_semana, dia_semana)
                        friendly_error = ValidationError(
                            _(
                                "Ya existe un horario activo y con turnos futuros programados para %(actividad)s los %(dia)s a las %(hora)02d:00."
                            )
                            % {"actividad": actividad, "dia": dia_nombre, "hora": hora}
                        )
                        self.add_error(None, friendly_error)

                    if non_unique_errors:
                        self._update_errors(ValidationError(non_unique_errors))
                    return

            self._update_errors(e)