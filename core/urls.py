from django.contrib import admin
from django.urls import path, include
from .views import home, contacto
from apps.accounts import views as accounts_views
from apps.turnos import views as turnos_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('panel/', accounts_views.panel_control, name='panel_control'),
    path('panel/turnos/', turnos_views.panel_turnos, name='panel_turnos'),
    path('panel/turnos/<int:pk>/editar/', turnos_views.editar_turno, name='editar_turno'),
    path('panel/turnos/editar/<int:actividad_id>/<str:fecha_str>/<int:hora>/', turnos_views.editar_turno_slot, name='editar_turno_slot'),
    path('panel/turnos/<int:pk>/eliminar/', turnos_views.eliminar_turno, name='eliminar_turno'),
    path('panel/turnos/eliminar/<int:actividad_id>/<str:fecha_str>/<int:hora>/', turnos_views.eliminar_turno_slot, name='eliminar_turno_slot'),
    # EMPLOYEE: Registrar Pago en Efectivo
    path('panel/buscar-reserva-pago/', accounts_views.buscar_reserva_para_pago, name='buscar_reserva_pago'),
    path('panel/registrar-pago/<int:reserva_id>/', accounts_views.registrar_pago_efectivo, name='registrar_pago_efectivo'),
    path('', home, name='home'),
    path('contacto/', contacto, name='contacto'),
    path("cuenta/", include("apps.accounts.urls")),
    path("turnos/", include("apps.turnos.urls")),
    path("pagos/", include("apps.pagos.urls")),
]
