from django.contrib import admin
from django.urls import path, include
from .views import home, contacto
from apps.accounts import views as accounts_views
from apps.turnos import views as turnos_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('panel/', accounts_views.panel_control, name='panel_control'),
    path('panel/turnos/', turnos_views.panel_turnos, name='panel_turnos'),
    path('panel/turnos/historial/', turnos_views.historial_clases_turnos, name='historial_clases_turnos'),
    path('panel/turnos/<int:pk>/editar/', turnos_views.editar_turno, name='editar_turno'),
    path('panel/turnos/editar/<int:actividad_id>/<str:fecha_str>/<int:hora>/', turnos_views.editar_turno_slot, name='editar_turno_slot'),
    path('panel/cancelar-clase/', turnos_views.cancelar_clase_paso_actividad, name='cancelar_clase_actividad'),
    path('panel/cancelar-clase/fecha/', turnos_views.cancelar_clase_paso_fecha, name='cancelar_clase_fecha'),
    path('panel/cancelar-clase/hora/', turnos_views.cancelar_clase_paso_hora, name='cancelar_clase_hora'),
    path('panel/cancelar-clase/revisar/', turnos_views.cancelar_clase_revisar, name='cancelar_clase_revisar'),
    path('panel/cancelar-clase/confirmar/', turnos_views.cancelar_clase_confirmar, name='cancelar_clase_confirmar'),
    path('', home, name='home'),
    path('contacto/', contacto, name='contacto'),
    path("cuenta/", include("apps.accounts.urls")),
    path("turnos/", include("apps.turnos.urls")),
    path("pagos/", include("apps.pagos.urls")),
    path("asistencia/", include("apps.asistencia.urls")),
]
