from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import GrupoReservaMensual, Reserva, Turno


class ReservaInline(admin.TabularInline):
    model  = Reserva
    extra  = 0
    fields = ("usuario", "estado", "tipo_reserva", "fecha_reserva", "fecha_cancelacion")
    readonly_fields = ("fecha_reserva", "fecha_cancelacion")
    show_change_link = True


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display  = ("actividad", "fecha", "hora", "cupos_ocupados_display", "cupos_libres_display", "esta_lleno")
    list_filter   = ("actividad", "fecha")
    search_fields = ("actividad__nombre",)
    ordering      = ("fecha", "hora")
    inlines       = [ReservaInline]

    @admin.display(description=_("Ocupados"))
    def cupos_ocupados_display(self, obj):
        return obj.cupos_ocupados

    @admin.display(description=_("Libres"), boolean=False)
    def cupos_libres_display(self, obj):
        return obj.cupos_libres

    @admin.display(description=_("Lleno"), boolean=True)
    def esta_lleno(self, obj):
        return obj.esta_lleno


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display   = ("usuario", "turno", "estado", "tipo_reserva", "fecha_reserva")
    list_filter    = ("estado", "tipo_reserva", "turno__actividad")
    search_fields  = ("usuario__email", "usuario__apellido", "turno__actividad__nombre")
    readonly_fields = ("fecha_reserva", "fecha_cancelacion")
    ordering       = ("-fecha_reserva",)


@admin.register(GrupoReservaMensual)
class GrupoReservaMensualAdmin(admin.ModelAdmin):
    list_display  = ("__str__", "usuario", "mes", "anio", "fecha_creacion", "cantidad_reservas")
    list_filter   = ("actividad", "anio", "mes")
    search_fields = ("usuario__email", "usuario__apellido")
    readonly_fields = ("fecha_creacion",)

    @admin.display(description=_("Reservas en grupo"))
    def cantidad_reservas(self, obj):
        return obj.reservas.count()