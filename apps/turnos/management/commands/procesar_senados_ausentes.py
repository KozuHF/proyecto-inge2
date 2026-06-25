from django.core.management.base import BaseCommand

from apps.asistencia.services import cancelar_abonados_ausentes_impagos, cancelar_senados_ausentes


class Command(BaseCommand):
    help = "Cancela reservas SEÑADO e abonos impagos cuya clase ya terminó y el cliente no asistió."

    def handle(self, *args, **options):
        n1 = cancelar_senados_ausentes()
        if n1:
            self.stdout.write(self.style.SUCCESS(f"Reservas SEÑADO canceladas por ausencia: {n1}"))
        else:
            self.stdout.write("No había reservas SEÑADO pendientes de cancelar.")

        n2 = cancelar_abonados_ausentes_impagos()
        if n2:
            self.stdout.write(self.style.SUCCESS(f"Reservas de abono impago canceladas por ausencia: {n2}"))
        else:
            self.stdout.write("No había abonos impagos pendientes de cancelar.")
