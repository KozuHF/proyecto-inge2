from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .forms import UsuarioCreacionForm, UsuarioModificacionForm
from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """
    Configuración del panel de administración para el modelo Usuario.
    Extiende UserAdmin para mantener el flujo estándar de Django
    (incluyendo el widget de cambio de contraseña segura).
    """

    add_form = UsuarioCreacionForm
    form = UsuarioModificacionForm
    model = Usuario

    list_display = (
        "id",
        "email",
        "nombre",
        "apellido",
        "nro_documento",
        "fecha_nacimiento",
        "is_active",
        "is_staff",
        "date_joined",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "nombre", "apellido", "nro_documento")
    ordering = ("apellido", "nombre")
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Datos personales"), {
            "fields": ("nombre", "apellido", "nro_documento", "fecha_nacimiento"),
        }),
        (_("Permisos"), {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        (_("Fechas"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "nombre",
                "apellido",
                "nro_documento",
                "fecha_nacimiento",
                "password1",
                "password2",
                "is_active",
                "is_staff",
            ),
        }),
    )