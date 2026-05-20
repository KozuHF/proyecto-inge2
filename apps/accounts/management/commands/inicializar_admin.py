"""
Crea o restablece el usuario administrador por defecto del proyecto.

Uso (desde la raíz Proyecto_Club360, con el venv activado):
    python manage.py inicializar_admin
    python manage.py inicializar_admin --password MiClaveSegura123
"""
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from apps.accounts.models import Roles, Usuario

EMAIL_DEFECTO = "admin@admin.com"
PASSWORD_DEFECTO = "Admin360!"


class Command(BaseCommand):
    help = "Crea o restablece el administrador por defecto (admin@admin.com)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=EMAIL_DEFECTO,
            help=f"Email del admin (default: {EMAIL_DEFECTO})",
        )
        parser.add_argument(
            "--password",
            default=PASSWORD_DEFECTO,
            help="Contraseña del admin (default: la del proyecto)",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]

        usuario, creado = Usuario.objects.get_or_create(
            email=email,
            defaults={
                "nombre": "Admin",
                "apellido": "Club360",
                "nro_documento": "00000000",
                "fecha_nacimiento": "2000-01-01",
                "rol": Roles.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        if not creado:
            usuario.rol = Roles.ADMIN
            usuario.is_staff = True
            usuario.is_superuser = True
            usuario.is_active = True

        usuario.password = make_password(password)
        usuario.save()

        accion = "creado" if creado else "actualizado"
        self.stdout.write(self.style.SUCCESS(f"Administrador {accion} correctamente."))
        self.stdout.write("")
        self.stdout.write("Credenciales:")
        self.stdout.write(f"  Email:      {email}")
        self.stdout.write(f"  Contraseña: {password}")
        self.stdout.write("")
        self.stdout.write("URLs de acceso (con runserver en http://127.0.0.1:8000/):")
        self.stdout.write("  App:        http://127.0.0.1:8000/cuenta/login/")
        self.stdout.write("  Django admin: http://127.0.0.1:8000/admin/")
        self.stdout.write("")
        self.stdout.write(
            "En ambos sitios el campo de usuario es el EMAIL (no escribas solo 'admin')."
        )
