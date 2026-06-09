from django.urls import path

from . import views

app_name = "asistencia"

urlpatterns = [
    path("reserva/<int:pk>/qr/", views.qr_reserva, name="qr_reserva"),
    path("escanear/", views.escanear, name="escanear"),
    path("marcar/<uuid:codigo>/", views.marcar, name="marcar"),
]
