from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import GrupoReservaMensual, HorarioDisponible, InvitacionCupo, Reserva, Turno


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


@admin.register(InvitacionCupo)
class InvitacionCupoAdmin(admin.ModelAdmin):
    list_display   = ("reserva", "estado", "fecha_envio", "fecha_vencimiento", "fecha_respuesta")
    list_filter    = ("estado",)
    search_fields  = ("reserva__usuario__email", "reserva__turno__actividad__nombre")
    readonly_fields = ("token", "fecha_envio", "fecha_respuesta")
    ordering       = ("-fecha_envio",)


@admin.register(GrupoReservaMensual)
class GrupoReservaMensualAdmin(admin.ModelAdmin):
    list_display  = ("__str__", "usuario", "mes", "anio", "fecha_creacion", "cantidad_reservas")
    list_filter   = ("actividad", "anio", "mes")
    search_fields = ("usuario__email", "usuario__apellido")
    readonly_fields = ("fecha_creacion",)

    @admin.display(description=_("Reservas en grupo"))
    def cantidad_reservas(self, obj):
        return obj.reservas.count()


@admin.register(HorarioDisponible)
class HorarioDisponibleAdmin(admin.ModelAdmin):
    """
    Panel de administración para gestionar los horarios disponibles.

    El admin elige:
      - Actividad
      - Día de la semana
      - Hora de inicio (el turno dura siempre 1 hora)
      - Cupos (opcional; si se omite, se hereda de la actividad)

    El sistema valida automáticamente que no haya solapamiento:
    solo puede existir un horario por actividad + día + hora.
    """

    list_display  = ("actividad", "dia_semana_display", "hora_display", "cupos_display", "precio", "activo")
    list_filter   = ("actividad", "dia_semana", "activo")
    search_fields = ("actividad__nombre",)
    ordering      = ("dia_semana", "hora", "actividad")
    list_editable = ("activo",)

    fieldsets = (
        (None, {
            "fields": ("actividad", "dia_semana", "hora"),
            "description": _(
                "Definí el día y horario del turno. "
                "Cada turno dura exactamente 1 hora. "
                "No puede haber dos horarios de la misma actividad en el mismo día y hora."
            ),
        }),
        (_("Configuración"), {
            "fields": ("cupos", "precio", "activo"),
        }),
    )

    @admin.display(description=_("Día"), ordering="dia_semana")
    def dia_semana_display(self, obj):
        from .models import DIAS_SEMANA_CHOICES
        return dict(DIAS_SEMANA_CHOICES).get(obj.dia_semana, obj.dia_semana)

    @admin.display(description=_("Horario"))
    def hora_display(self, obj):
        return f"{obj.hora:02d}:00 – {obj.hora + 1:02d}:00"

    @admin.display(description=_("Cupos"))
    def cupos_display(self, obj):
        if obj.cupos is not None:
            return obj.cupos
        return _("%(cupos)s (actividad)") % {"cupos": obj.actividad.cupos}

    def save_model(self, request, obj, form, change):
        """
        Llama a full_clean() para validar solapamiento y, si es un horario nuevo
        o se acaba de reactivar, genera los Turno de los próximos 6 meses.
        """
        from . import services

        estaba_inactivo = change and not obj.__class__.objects.filter(pk=obj.pk, activo=True).exists()
        obj.full_clean()
        super().save_model(request, obj, form, change)

        es_nuevo = not change
        se_reactivo = change and estaba_inactivo and obj.activo

        if es_nuevo or se_reactivo:
            creados, omitidos = services.generar_turnos_desde_horario(obj, meses=120)
            accion = "creado" if es_nuevo else "reactivado"
            self.message_user(
                request,
                _(
                    "Horario %(accion)s. Se generaron %(creados)d turno(s) "
                    "(%(omitidos)d fecha(s) omitida(s) por ser feriado o ya existir)."
                ) % {"accion": accion, "creados": creados, "omitidos": omitidos},
            )