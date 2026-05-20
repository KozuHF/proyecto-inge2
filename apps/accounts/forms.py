from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField, AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Usuario, validar_mayor_de_edad


class UsuarioCreacionForm(forms.ModelForm):
    """
    Formulario para crear un nuevo usuario.
    Incluye doble campo de contraseña y validaciones de seguridad.
    """

    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        min_length=8,
        help_text=_(
            "Mínimo 8 caracteres. Debe incluir mayúsculas, minúsculas, "
            "números y caracteres especiales."
        ),
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    declaracion_salud = forms.BooleanField(
        label=_("Declaro bajo juramento que me encuentro en condiciones físicas para la práctica deportiva y no poseo impedimentos médicos."),
        required=True,
        error_messages={'required': _("Debe aceptar la declaración de salud para registrarse.")}
    )

    class Meta:
        model = Usuario
        fields = (
            "nombre",
            "apellido",
            "nro_documento",
            "email",
            "fecha_nacimiento",
        )
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get("fecha_nacimiento")
        if fecha:
            validar_mayor_de_edad(fecha)
        return fecha

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        self._validar_fortaleza_password(password)
        return password

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Las contraseñas no coinciden."))
        return p2

    def _validar_fortaleza_password(self, password):
        """Aplica validaciones de seguridad básicas sobre la contraseña."""
        if not password:
            return
        errores = []
        if not any(c.isupper() for c in password):
            errores.append(_("Debe contener al menos una letra mayúscula."))
        if not any(c.islower() for c in password):
            errores.append(_("Debe contener al menos una letra minúscula."))
        if not any(c.isdigit() for c in password):
            errores.append(_("Debe contener al menos un número."))
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
            errores.append(_("Debe contener al menos un carácter especial."))
        if errores:
            raise ValidationError(errores)

    def save(self, commit=True):
        usuario = super().save(commit=False)
        # set_password aplica PBKDF2+SHA256 con salt aleatorio
        usuario.set_password(self.cleaned_data["password1"])
        if commit:
            usuario.save()
        return usuario


class UsuarioModificacionForm(forms.ModelForm):
    """
    Formulario para modificar datos de un usuario existente.
    La contraseña se gestiona por separado para mayor seguridad.
    """

    password = ReadOnlyPasswordHashField(
        label=_("Contraseña"),
        help_text=_("Las contraseñas no se almacenan en texto plano."),
    )

    class Meta:
        model = Usuario
        fields = (
            "nombre",
            "apellido",
            "nro_documento",
            "email",
            "fecha_nacimiento",
            "password",
            "is_active",
            "is_staff",
        )
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get("fecha_nacimiento")
        if fecha:
            validar_mayor_de_edad(fecha)
        return fecha

    def clean_password(self):
        # El campo es de solo lectura; devolvemos el valor original
        return self.initial.get("password")


class CambiarPasswordForm(forms.Form):
    """Formulario para que el usuario cambie su propia contraseña."""

    password_actual = forms.CharField(
        label=_("Contraseña actual"),
        widget=forms.PasswordInput(),
    )
    password_nueva = forms.CharField(
        label=_("Nueva contraseña"),
        widget=forms.PasswordInput(),
        min_length=8,
    )
    password_confirmacion = forms.CharField(
        label=_("Confirmar nueva contraseña"),
        widget=forms.PasswordInput(),
    )

    def __init__(self, usuario, *args, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean_password_actual(self):
        password = self.cleaned_data.get("password_actual")
        if not self.usuario.check_password(password):
            raise ValidationError(_("La contraseña actual es incorrecta."))
        return password

    def clean_password_nueva(self):
        password = self.cleaned_data.get("password_nueva")
        self._validar_fortaleza_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password_nueva")
        p2 = cleaned.get("password_confirmacion")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Las contraseñas nuevas no coinciden."))
        return cleaned

    def _validar_fortaleza_password(self, password):
        if not password:
            return
        errores = []
        if not any(c.isupper() for c in password):
            errores.append(_("Debe contener al menos una letra mayúscula."))
        if not any(c.islower() for c in password):
            errores.append(_("Debe contener al menos una letra minúscula."))
        if not any(c.isdigit() for c in password):
            errores.append(_("Debe contener al menos un número."))
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
            errores.append(_("Debe contener al menos un carácter especial."))
        if errores:
            raise ValidationError(errores)

    def save(self):
        self.usuario.set_password(self.cleaned_data["password_nueva"])
        self.usuario.save()
        return self.usuario


class UsuarioFiltroForm(forms.Form):
    """Formulario para búsqueda/filtrado de usuarios."""

    nombre = forms.CharField(required=False, label=_("Nombre"))
    apellido = forms.CharField(required=False, label=_("Apellido"))
    email = forms.EmailField(required=False, label=_("Email"))
    nro_documento = forms.CharField(required=False, label=_("Nro. documento"))
    fecha_nacimiento_desde = forms.DateField(
        required=False,
        label=_("Nacimiento desde"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    fecha_nacimiento_hasta = forms.DateField(
        required=False,
        label=_("Nacimiento hasta"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    is_active = forms.NullBooleanField(
        required=False,
        label=_("Activo"),
        widget=forms.Select(
            choices=[("", "Todos"), ("True", "Activos"), ("False", "Inactivos")]
        ),
    )