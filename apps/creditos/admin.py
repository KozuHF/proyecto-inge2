from django.contrib import admin

from .models import Credito


@admin.register(Credito)
class CreditoAdmin(admin.ModelAdmin):
    list_display = (
        "usuario",
        "actividad",
        "fecha_otorgamiento",
        "fecha_vencimiento",
        "consumido_en",
    )
    list_filter = ("actividad", "consumido_en")
    search_fields = ("usuario__email", "usuario__nombre", "usuario__apellido")
    readonly_fields = ("fecha_otorgamiento",)
