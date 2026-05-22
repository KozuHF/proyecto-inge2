from django.core.management.base import BaseCommand

from apps.turnos import services


class Command(BaseCommand):
    help = (
        "Cancela abonos mensuales de primera quincena impagos tras el día 11 "
        "y suspende a los usuarios afectados."
    )

    def handle(self, *args, **options):
        n = services.verificar_plazos_abonos_mensuales()
        self.stdout.write(
            self.style.SUCCESS(f"Verificación completada. Sanciones aplicadas: {n}")
        )
