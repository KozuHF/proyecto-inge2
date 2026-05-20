from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TurnosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.turnos"
    verbose_name = _("Turnos")