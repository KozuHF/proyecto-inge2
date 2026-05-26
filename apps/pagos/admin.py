from django.contrib import admin

from .models import Pago, TarjetaGuardada


@admin.register(TarjetaGuardada)
class TarjetaGuardadaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "ultimos_4", "titular", "vencimiento", "fecha_actualizacion")
    search_fields = ("usuario__email", "titular", "ultimos_4")
    readonly_fields = ("pan", "fecha_actualizacion")


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("referencia", "reserva", "usuario", "monto", "tipo_cobro", "estado", "ultimos_4", "fecha")
    list_filter = ("estado", "fecha")
    search_fields = ("referencia", "usuario__email", "ultimos_4")
    readonly_fields = ("fecha",)
