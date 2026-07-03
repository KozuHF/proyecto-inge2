from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    ReadOnlyPasswordHashField,
    SetPasswordForm,
)
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Usuario, validar_mayor_de_edad, Roles

INPUT_CLASS = (
    "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
    "focus:ring-green-500 focus:border-green-500 block w-full p-2.5"
)

PANEL_INPUT_CLASS = (
    "bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg "
    "focus:ring-green-500 focus:border-green-500 block w-full p-2.5 "
    "dark:bg-gray-700 dark:border-gray-600 dark:text-white dark:placeholder-gray-400 "
    "dark:focus:ring-green-500 dark:focus:border-green-500"
)

PASSWORD_HELP_TEXT = _(
    "Mínimo 8 caracteres. Debe incluir mayúsculas, minúsculas, "
    "números y caracteres especiales."
)


def validar_fortaleza_password(password):
    """Validaciones de seguridad compartidas para contraseñas nuevas."""
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


class LoginForm(AuthenticationForm):
    """Login con email (USERNAME_FIELD del modelo Usuario)."""

    username = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "tu@email.com",
                "class": INPUT_CLASS,
            }
        ),
    )
    password = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "••••••••",
                "class": INPUT_CLASS,
            }
        ),
    )

    error_messages = {
        "invalid_login": _("Email o contraseña incorrectos."),
        "inactive": _("Esta cuenta está desactivada."),
    }

    def clean(self):
        if self.cleaned_data.get("username"):
            self.cleaned_data["username"] = self.cleaned_data["username"].strip().lower()
        return super().clean()


class UsuarioCreacionForm(forms.ModelForm):
    """
    Formulario para crear un nuevo usuario.
    Incluye doble campo de contraseña y validaciones de seguridad.
    """

    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                "autocomplete": "new-password",
                "placeholder": "••••••••",
                "class": INPUT_CLASS,
            }
        ),
        min_length=8,
        help_text=PASSWORD_HELP_TEXT,
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                "autocomplete": "new-password",
                "placeholder": "••••••••",
                "class": INPUT_CLASS,
            }
        ),
    )
    acepta_sin_impedimentos = forms.BooleanField(
        label=_("Acepto que no poseo impedimentos físicos"),
        required=True,
        error_messages={
            "required": _("Es obligatorio marcar esta casilla para registrarse."),
        },
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "w-4 h-4 mt-0.5 text-green-600 bg-gray-50 border-gray-300 rounded "
                    "focus:ring-green-500 focus:ring-2"
                ),
            }
        ),
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
            "nombre": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Juan"}),
            "apellido": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Pérez"}),
            "nro_documento": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "12345678"}),
            "email": forms.EmailInput(
                attrs={"class": INPUT_CLASS, "placeholder": "tu@email.com", "autocomplete": "email"}
            ),
            "fecha_nacimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": INPUT_CLASS}
            ),
        }
        error_messages = {
            "nro_documento": {
                "unique": _("Este número de documento ya se encuentra registrado."),
            }
        }

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get("fecha_nacimiento")
        if fecha:
            validar_mayor_de_edad(fecha)
        return fecha

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        validar_fortaleza_password(password)
        return password

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Las contraseñas no coinciden."))
        return p2

    def clean_email(self):
        email = _normalizar_email(self.cleaned_data.get("email"))
        if email and _email_en_uso(email):
            raise ValidationError(_("Este correo ya se encuentra en uso."))
        return email

    def clean_acepta_sin_impedimentos(self):
        if not self.cleaned_data.get("acepta_sin_impedimentos"):
            raise ValidationError(
                _("Es obligatorio marcar esta casilla para registrarse.")
            )
        return True

    def save(self, commit=True):
        usuario = super().save(commit=False)
        # set_password aplica PBKDF2+SHA256 con salt aleatorio
        usuario.set_password(self.cleaned_data["password1"])
        if commit:
            usuario.save()
        return usuario


def _normalizar_email(email):
    """Estandariza el email a minúsculas y sin espacios."""
    return email.strip().lower() if email else email


def _email_en_uso(email, excluir_pk=None):
    qs = Usuario.objects.filter(email__iexact=email)
    if excluir_pk:
        qs = qs.exclude(pk=excluir_pk)
    return qs.exists()


class UsuarioPerfilForm(forms.ModelForm):
    """
    Edición de la propia cuenta: el usuario puede modificar nombre, apellido
    y email. El DNI y la fecha de nacimiento son fijos y se muestran como
    información de solo lectura en el template.
    """

    class Meta:
        model = Usuario
        fields = ("nombre", "apellido", "email")
        widgets = {
            "nombre": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "apellido": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "email": forms.EmailInput(
                attrs={"class": INPUT_CLASS, "autocomplete": "email"}
            ),
        }

    def clean_email(self):
        email = _normalizar_email(self.cleaned_data.get("email"))
        if email and _email_en_uso(email, excluir_pk=self.instance.pk):
            raise ValidationError(_("Este correo ya se encuentra en uso."))
        return email


class UsuarioModificacionForm(forms.ModelForm):
    """
    Formulario para modificar datos de un usuario existente (staff).
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
            "nombre": forms.TextInput(attrs={"class": PANEL_INPUT_CLASS}),
            "apellido": forms.TextInput(attrs={"class": PANEL_INPUT_CLASS}),
            "nro_documento": forms.TextInput(attrs={"class": PANEL_INPUT_CLASS}),
            "email": forms.EmailInput(
                attrs={"class": PANEL_INPUT_CLASS, "autocomplete": "email"}
            ),
            "fecha_nacimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": PANEL_INPUT_CLASS}
            ),
        }

    def clean_email(self):
        email = _normalizar_email(self.cleaned_data.get("email"))
        if email and _email_en_uso(email, excluir_pk=self.instance.pk):
            raise ValidationError(_("Este correo ya se encuentra en uso."))
        return email

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
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASS, "autocomplete": "current-password"}),
    )
    password_nueva = forms.CharField(
        label=_("Nueva contraseña"),
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASS, "autocomplete": "new-password"}),
        min_length=8,
    )
    password_confirmacion = forms.CharField(
        label=_("Confirmar nueva contraseña"),
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASS, "autocomplete": "new-password"}),
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
        validar_fortaleza_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password_nueva")
        p2 = cleaned.get("password_confirmacion")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Las contraseñas nuevas no coinciden."))
        return cleaned

    def save(self):
        self.usuario.set_password(self.cleaned_data["password_nueva"])
        self.usuario.save()
        return self.usuario


class RecuperarPasswordForm(PasswordResetForm):
    """Solicitud de enlace de recuperación por email."""

    email = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "tu@email.com",
                "class": INPUT_CLASS,
            }
        ),
    )


class RestablecerPasswordForm(SetPasswordForm):
    """Nueva contraseña tras abrir el enlace del correo."""

    error_messages = {
        **SetPasswordForm.error_messages,
        "password_mismatch": _("Las contraseñas no coinciden."),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("new_password1", "new_password2"):
            self.fields[name].widget.attrs.update(
                {
                    "autocomplete": "new-password",
                    "placeholder": "••••••••",
                    "class": INPUT_CLASS,
                }
            )
        self.fields["new_password1"].help_text = PASSWORD_HELP_TEXT
        self.fields["new_password1"].label = _("Nueva contraseña")
        self.fields["new_password2"].label = _("Confirmar nueva contraseña")

    def clean(self):
        cleaned_data = super().clean()
        password = self.cleaned_data.get("new_password1")
        if password:
            try:
                validar_fortaleza_password(password)
            except ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned_data


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


class EmpleadoCreacionForm(forms.ModelForm):
    """
    Formulario para crear un nuevo empleado desde el panel de administración.
    No incluye el checkbox de impedimentos físicos ya que es para personal del club.
    """
    password1 = forms.CharField(
        label=_("Contraseña"),
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                "autocomplete": "new-password",
                "placeholder": "••••••••",
                "class": PANEL_INPUT_CLASS,
            }
        ),
        min_length=8,
        help_text=PASSWORD_HELP_TEXT,
    )
    password2 = forms.CharField(
        label=_("Confirmar contraseña"),
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                "autocomplete": "new-password",
                "placeholder": "••••••••",
                "class": PANEL_INPUT_CLASS,
            }
        ),
    )

    class Meta:
        model = Usuario
        fields = (
            "nombre",
            "apellido",
            "email",
        )
        widgets = {
            "nombre": forms.TextInput(attrs={"class": PANEL_INPUT_CLASS, "placeholder": "Juan"}),
            "apellido": forms.TextInput(attrs={"class": PANEL_INPUT_CLASS, "placeholder": "Pérez"}),
            "email": forms.EmailInput(
                attrs={"class": PANEL_INPUT_CLASS, "placeholder": "tu@email.com", "autocomplete": "email"}
            ),
        }

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        validar_fortaleza_password(password)
        return password

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Las contraseñas no coinciden."))
        return p2

    def clean_email(self):
        email = _normalizar_email(self.cleaned_data.get("email"))
        if email and _email_en_uso(email):
            raise ValidationError(_("Este correo ya se encuentra en uso."))
        return email

    def save(self, commit=True):
        import random
        from datetime import timedelta
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["password1"])
        usuario.rol = Roles.EMPLOYEE
        usuario.is_staff = True  # Empleados tienen acceso de staff en Django

        # Generar un nro_documento único de 8 dígitos comenzando con 99
        while True:
            random_digits = "".join(str(random.randint(0, 9)) for _ in range(6))
            dni = f"99{random_digits}"
            if not Usuario.objects.filter(nro_documento=dni).exists():
                usuario.nro_documento = dni
                break

        # Generar una fecha de nacimiento por defecto (exactamente 20 años atrás)
        hoy = timezone.now().date()
        try:
            fecha_defecto = hoy.replace(year=hoy.year - 20)
        except ValueError:
            # En años bisiestos si hoy es 29 de febrero
            fecha_defecto = hoy - timedelta(days=365 * 20)
        usuario.fecha_nacimiento = fecha_defecto

        if commit:
            usuario.save()
        return usuario
