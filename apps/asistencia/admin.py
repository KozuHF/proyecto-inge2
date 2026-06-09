from django.contrib import admin

from .models import Asistencia


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("reserva", "presente", "fecha_registro", "registrado_por")
    list_filter = ("presente",)
    search_fields = ("reserva__usuario__email", "codigo")
    readonly_fields = ("codigo",)
