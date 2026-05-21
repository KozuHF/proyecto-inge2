from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Actividad


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    """
    Administración de actividades.

    Solo permite modificar los cupos (y el precio cuando se implemente).
    No se pueden crear ni eliminar actividades desde aquí.
    """

    list_display  = ("get_nombre_display", "cupos", "precio_turno")
    list_editable = ("cupos", "precio_turno")
    ordering      = ("nombre",)

    # ── Bloquear creación / eliminación ──────────────────────────────────────
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ── Solo cupos es editable ────────────────────────────────────────────────
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("nombre",)
        return ()

    @admin.display(description=_("Actividad"))
    def get_nombre_display(self, obj):
        return obj.get_nombre_display()