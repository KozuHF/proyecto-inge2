"""
Seed de usuarios para testing.

Crea 1 usuario administrador (superuser) y 20 usuarios comunes
con credenciales simples y predecibles, ideales para probar el sistema.

Uso:
    python manage.py seed_users           # Crea admin + 20 usuarios (idempotente)
    python manage.py seed_users --reset   # Borra los usuarios de prueba y los recrea

Credenciales generadas:
    Admin    -> admin@test.com   /  Admin123!
    Usuarios -> user01@test.com .. user20@test.com  /  User123!
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Usuario, Roles


# ---------------------------------------------------------------------------
# Configuración de credenciales (cambiar aquí si se desea)
# ---------------------------------------------------------------------------
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "Admin123!"

USER_PASSWORD = "User123!"
USER_EMAIL_TEMPLATE = "user{:02d}@test.com"  # user01@test.com ... user20@test.com
CANTIDAD_USUARIOS = 20

# Datos ficticios para que los registros se vean realistas
NOMBRES = [
    "Juan", "María", "Carlos", "Ana", "Lucía", "Pedro", "Sofía", "Diego",
    "Valentina", "Martín", "Camila", "Federico", "Julieta", "Tomás",
    "Florencia", "Nicolás", "Agustina", "Matías", "Brenda", "Lautaro",
]
APELLIDOS = [
    "Pérez", "García", "Rodríguez", "Fernández", "López", "Martínez",
    "González", "Sánchez", "Romero", "Díaz", "Torres", "Álvarez",
    "Ruiz", "Ramírez", "Flores", "Acosta", "Benítez", "Castro",
    "Medina", "Sosa",
]


class Command(BaseCommand):
    help = "Crea un usuario admin y 20 usuarios de prueba con credenciales simples."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Elimina los usuarios de prueba previos antes de recrearlos.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._eliminar_usuarios_prueba()

        self._crear_admin()
        creados = self._crear_usuarios()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== SEED COMPLETADO ==="))
        self.stdout.write(self.style.SUCCESS(
            f"Admin    -> {ADMIN_EMAIL}   /  {ADMIN_PASSWORD}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Usuarios -> user01..user{CANTIDAD_USUARIOS:02d}@test.com  /  {USER_PASSWORD}  "
            f"({len(creados)} nuevos)"
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _eliminar_usuarios_prueba(self):
        qs = Usuario.objects.filter(email__endswith="@test.com")
        cantidad = qs.count()
        qs.delete()
        if cantidad:
            self.stdout.write(self.style.WARNING(
                f"Se eliminaron {cantidad} usuarios previos de prueba."
            ))

    def _crear_admin(self):
        if Usuario.objects.filter(email=ADMIN_EMAIL).exists():
            self.stdout.write(self.style.WARNING(
                f"Admin '{ADMIN_EMAIL}' ya existía. Se omite."
            ))
            return

        admin = Usuario.objects.create_superuser(
            email=ADMIN_EMAIL,
            nombre="Admin",
            apellido="Sistema",
            nro_documento="00000001",
            fecha_nacimiento=date(1990, 1, 1),
            password=ADMIN_PASSWORD,
        )
        self.stdout.write(self.style.SUCCESS(f"+ Admin creado: {admin.email}"))

    def _crear_usuarios(self):
        creados = []
        for i in range(1, CANTIDAD_USUARIOS + 1):
            email = USER_EMAIL_TEMPLATE.format(i)

            if Usuario.objects.filter(email=email).exists():
                continue

            nombre = NOMBRES[(i - 1) % len(NOMBRES)]
            apellido = APELLIDOS[(i - 1) % len(APELLIDOS)]

            usuario = Usuario.objects.create_user(
                email=email,
                nombre=nombre,
                apellido=apellido,
                nro_documento=f"{10000000 + i}",  # DNI único: 10000001..10000020
                fecha_nacimiento=date(1995, 6, 15),
                password=USER_PASSWORD,
                rol=Roles.USER,
            )
            creados.append(usuario)
            self.stdout.write(f"  + {usuario.email}  ({nombre} {apellido})")

        return creados