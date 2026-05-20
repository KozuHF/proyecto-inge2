from django.contrib import admin
from django.urls import path, include
from .views import home

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path("cuenta/", include("apps.accounts.urls")),
    path("turnos/", include("apps.turnos.urls")),
]
