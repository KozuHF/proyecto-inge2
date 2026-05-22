from django.core.management.base import BaseCommand

from apps.creditos import services


class Command(BaseCommand):
    help = "Elimina créditos no usados que superaron los 30 días de validez."

    def handle(self, *args, **options):
        n = services._eliminar_vencidos_sin_usar()
        self.stdout.write(
            self.style.SUCCESS(f"Créditos vencidos eliminados: {n}")
        )
