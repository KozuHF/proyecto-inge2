from django.urls import path

from . import views

app_name = "pagos"

urlpatterns = [
    path("reservar/", views.pagar_wizard, name="pagar_wizard"),
    path("reservar/cancelar/", views.cancelar_checkout, name="cancelar_checkout"),
    path("reserva/<int:reserva_id>/", views.pagar_reserva, name="pagar_reserva"),
    path("grupo/<int:grupo_id>/", views.pagar_grupo, name="pagar_grupo"),
]
