from django.urls import path

from . import views

app_name = "pagos"

urlpatterns = [
    path("reserva/<int:reserva_id>/", views.pagar_reserva, name="pagar_reserva"),
]
