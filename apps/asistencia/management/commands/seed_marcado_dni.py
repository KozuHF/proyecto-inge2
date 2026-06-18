"""
Crea entidades de prueba para la funcionalidad de marcado de asistencia por DNI.

Genera un empleado y clientes de prueba con reservas, de modo de poder probar a
mano la pantalla Panel -> Marcar por DNI:

- Un cliente con una clase EN CURSO (cae en la ventana de asistencia ahora) -> marcable.
- Un cliente con una clase de hoy FUERA del horario actual -> no marcable.

Es idempotente: borra los datos de prueba previos (por documento) y los recrea.

Uso:
    python manage.py seed_marcado_dni
    python manage.py seed_marcado_dni --password MiClave123
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.turnos.models import Reserva, Turno

# Documentos reservados para los datos de prueba (se borran y recrean).
DOC_EMPLEADO = "88000001"
DOC_CLIENTE_EN_CURSO = "88000010"
DOC_CLIENTE_FUERA = "88000011"
DOC_CLIENTE_SENADO = "88000012"
PASSWORD_DEFECTO = "Prueba360!"


class Command(BaseCommand):
    help = "Crea datos de prueba para el marcado de asistencia por DNI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=PASSWORD_DEFECTO,
            help="Contraseña para el empleado de prueba (default: %(default)s).",
        )

    def handle(self, *args, **options):
        password = options["password"]
        docs = [DOC_EMPLEADO, DOC_CLIENTE_EN_CURSO, DOC_CLIENTE_FUERA, DOC_CLIENTE_SENADO]

        # Idempotencia: borrar datos de prueba previos (cascadea reservas/asistencias).
        Usuario.objects.filter(nro_documento__in=docs).delete()

        empleado = Usuario.objects.create_user(
            email="empleado.prueba@club360.test", nombre="Empleado", apellido="Prueba",
            nro_documento=DOC_EMPLEADO, fecha_nacimiento=date(1990, 1, 1),
            password=password, rol=Roles.EMPLOYEE, is_staff=True,
        )
        cliente_ok = Usuario.objects.create_user(
            email="cliente.encurso@club360.test", nombre="Carla", apellido="EnCurso",
            nro_documento=DOC_CLIENTE_EN_CURSO, fecha_nacimiento=date(1995, 5, 5),
            password=password, rol=Roles.USER,
        )
        cliente_fuera = Usuario.objects.create_user(
            email="cliente.fuera@club360.test", nombre="Fabio", apellido="FueraDeHora",
            nro_documento=DOC_CLIENTE_FUERA, fecha_nacimiento=date(1992, 2, 2),
            password=password, rol=Roles.USER,
        )
        cliente_senado = Usuario.objects.create_user(
            email="cliente.senado@club360.test", nombre="Sofía", apellido="SoloSeña",
            nro_documento=DOC_CLIENTE_SENADO, fecha_nacimiento=date(1993, 3, 3),
            password=password, rol=Roles.USER,
        )

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL, defaults={"cupos": 10, "precio_turno": 5000}
        )

        hoy = timezone.localdate()
        hora_actual = timezone.localtime().hour
        # Una hora de hoy bien lejos de la actual para quedar fuera de la ventana.
        hora_lejana = 20 if hora_actual < 14 else 8

        turno_en_curso = self._turno(actividad, hoy, hora_actual)
        turno_fuera = self._turno(actividad, hoy, hora_lejana)

        self._reserva_paga(cliente_ok, turno_en_curso)
        self._reserva_paga(cliente_fuera, turno_fuera)
        # En curso pero solo señó (50%): no es marcable hasta pagar el total.
        self._reserva_senada(cliente_senado, turno_en_curso)

        self.stdout.write(self.style.SUCCESS("Datos de prueba creados.\n"))
        self.stdout.write("Empleado (para iniciar sesión):")
        self.stdout.write(f"  email:    {empleado.email}")
        self.stdout.write(f"  password: {password}\n")
        self.stdout.write("Probar en: Panel -> Marcar por DNI  (/asistencia/marcar-dni/)\n")
        self.stdout.write("Casos de prueba:")
        self.stdout.write(
            f"  DNI {DOC_CLIENTE_EN_CURSO}  -> {cliente_ok.get_full_name()}: "
            f"clase de hoy {hora_actual:02d}:00, EN CURSO -> se puede marcar."
        )
        self.stdout.write(
            f"  DNI {DOC_CLIENTE_FUERA}  -> {cliente_fuera.get_full_name()}: "
            f"clase de hoy {hora_lejana:02d}:00, fuera de horario -> NO marcable."
        )
        self.stdout.write(
            f"  DNI {DOC_CLIENTE_SENADO}  -> {cliente_senado.get_full_name()}: "
            f"clase de hoy {hora_actual:02d}:00 EN CURSO pero solo señada (50%) "
            f"-> NO marcable hasta pagar el total."
        )
        self.stdout.write(
            "  DNI 00000000          -> inexistente -> mensaje 'No se encontró'."
        )

    def _turno(self, actividad, fecha, hora) -> Turno:
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=fecha, hora=hora, defaults={"cupos": 10}
        )
        return turno

    def _reserva_paga(self, usuario, turno) -> Reserva:
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.PAGADO,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
            precio_abonado=turno.precio_efectivo,
        )

    def _reserva_senada(self, usuario, turno) -> Reserva:
        """Reserva confirmada con solo la seña (50%) abonada."""
        sena = (turno.precio_efectivo * Decimal("0.5")).quantize(Decimal("0.01"))
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
            precio_abonado=sena,
        )
