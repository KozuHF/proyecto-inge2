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
    path("mis-reservas/<int:pk>/cancelar/", views.cancelar_reserva, name="cancelar_reserva"),
    path("grupos/<int:pk>/cancelar/", views.cancelar_grupo_mensual, name="cancelar_grupo_mensual"),
]
