from django.core.management.base import BaseCommand

from apps.turnos import lista_espera


class Command(BaseCommand):
    help = (
        "Vence las invitaciones de cupo cuyo plazo ya pasó, libera el lugar y "
        "se lo ofrece al siguiente de la lista de espera. Pensado para correr "
        "periódicamente (ej. cada minuto vía Task Scheduler)."
    )

    def handle(self, *args, **options):
        n = lista_espera.expirar_invitaciones_vencidas()
        self.stdout.write(
            self.style.SUCCESS(f"Invitaciones vencidas procesadas: {n}")
        )
