from django.contrib import admin

from .models import SaldoCredito


@admin.register(SaldoCredito)
class SaldoCreditoAdmin(admin.ModelAdmin):
    list_display = ("usuario", "actividad", "cantidad")
    list_filter = ("actividad",)
    search_fields = ("usuario__email", "usuario__nombre", "usuario__apellido")
