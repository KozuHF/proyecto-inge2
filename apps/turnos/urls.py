from django.urls import path
from . import views

app_name = "turnos"

urlpatterns = [
    path("reservar/", views.paso_tipo_abono, name="paso_tipo_abono"),
    path("reservar/actividad/", views.paso_actividad, name="paso_actividad"),
    path("reservar/fecha/", views.paso_fecha, name="paso_fecha"),
    path("reservar/hora/", views.paso_hora, name="paso_hora"),
    path("reservar/confirmar/", views.paso_confirmar, name="paso_confirmar"),
    path("reservar/fechas/", views.paso_seleccion_fechas, name="paso_seleccion_fechas"),

    path("mis-reservas/", views.mis_reservas, name="mis_reservas"),
    path("mis-reservas/historial/", views.historial_clases, name="historial_clases"),
    path("mis-reservas/<int:pk>/cancelar/", views.cancelar_reserva, name="cancelar_reserva"),
    path("grupos/<int:pk>/cancelar/", views.cancelar_grupo_mensual, name="cancelar_grupo_mensual"),

    # ── Invitaciones de cupo (lista de espera) ────────────────────────────────
    path("invitacion/<uuid:token>/", views.invitacion_detalle, name="invitacion_detalle"),
    path("invitacion/<uuid:token>/aceptar/", views.invitacion_aceptar, name="invitacion_aceptar"),
    path("invitacion/<uuid:token>/rechazar/", views.invitacion_rechazar, name="invitacion_rechazar"),

    # ── Gestión de horarios disponibles (solo admin) ──────────────────────────
    path("horarios/crear/", views.crear_horario_disponible, name="crear_horario_disponible"),
    path("horarios/<int:pk>/editar/", views.editar_horario_disponible, name="editar_horario_disponible"),
    path("horarios/<int:pk>/eliminar/", views.eliminar_horario_disponible, name="eliminar_horario_disponible"),
]