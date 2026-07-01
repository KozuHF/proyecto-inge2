from django.core.management.base import BaseCommand

from apps.asistencia.services import cancelar_abonados_ausentes_impagos, cancelar_individuales_ausentes_impagos


class Command(BaseCommand):
    help = "Cancela reservas individuales e abonos impagos cuya clase ya terminó y el cliente no asistió."

    def handle(self, *args, **options):
        n1 = cancelar_individuales_ausentes_impagos()
        if n1:
            self.stdout.write(self.style.SUCCESS(f"Reservas individuales canceladas por ausencia: {n1}"))
        else:
            self.stdout.write("No había reservas individuales pendientes de cancelar.")

        n2 = cancelar_abonados_ausentes_impagos()
        if n2:
            self.stdout.write(self.style.SUCCESS(f"Reservas de abono impago canceladas por ausencia: {n2}"))
        else:
            self.stdout.write("No había abonos impagos pendientes de cancelar.")
