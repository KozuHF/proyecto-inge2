"""
Seed para probar la asistencia por QR.

Crea (de forma idempotente):
  - 1 cliente  -> qr_cliente@test.com  / Cliente123!
  - 1 empleado -> qr_empleado@test.com / Empleado123!
  - 1 actividad (Fútbol) si no existe
  - 1 turno para HOY
  - 1 reserva del cliente CONFIRMADA y PAGADA POR COMPLETO en ese turno
  - la Asistencia asociada (con su código/URL de QR listo)

Uso:
    python manage.py seed_asistencia            # crea/asegura los objetos
    python manage.py seed_asistencia --reset    # borra los de prueba y recrea
    python manage.py seed_asistencia --hora 18  # elige la hora del turno (8..21)

Al terminar imprime las credenciales, el id de la reserva y la URL de marcado.
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.turnos.models import Turno, Reserva
from apps.asistencia import services

CLIENTE_EMAIL = "qr_cliente@test.com"
CLIENTE_PASSWORD = "Cliente123!"
EMPLEADO_EMAIL = "qr_empleado@test.com"
EMPLEADO_PASSWORD = "Empleado123!"


class Command(BaseCommand):
    help = "Crea los objetos necesarios para probar la asistencia por QR (turno de hoy, reserva pagada, etc.)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Elimina los objetos de prueba previos antes de recrearlos.")
        parser.add_argument("--hora", type=int, default=None,
                            help="Hora del turno de hoy (8..21). Por defecto usa la hora actual acotada al rango.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        cliente = self._crear_usuario(
            CLIENTE_EMAIL, CLIENTE_PASSWORD, "QRCliente", "Prueba", "90000001", Roles.USER, staff=False
        )
        empleado = self._crear_usuario(
            EMPLEADO_EMAIL, EMPLEADO_PASSWORD, "QREmpleado", "Prueba", "90000002", Roles.EMPLOYEE, staff=True
        )

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL, defaults={"cupos": 20, "precio_turno": 5000}
        )

        hoy = timezone.localdate()
        hora = options["hora"]
        if hora is None:
            # Hora actual: así "ahora" cae dentro de la ventana de asistencia
            # (desde 30 min antes del inicio hasta que termina la clase).
            hora = timezone.localtime().hour

        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=hoy, hora=hora,
            defaults={"cupos": actividad.cupos},
        )

        reserva, creada = Reserva.objects.get_or_create(
            usuario=cliente, turno=turno,
            defaults={
                "estado": Reserva.Estado.CONFIRMADA,
                "estado_pago": Reserva.EstadoPago.PAGADO,
                "tipo_reserva": Reserva.TipoReserva.INDIVIDUAL,
                "precio_abonado": actividad.precio_turno,
                "referencia_pago": "SEED-QR",
            },
        )
        if not creada:
            # Asegura que quede confirmada y pagada por completo
            reserva.estado = Reserva.Estado.CONFIRMADA
            reserva.estado_pago = Reserva.EstadoPago.PAGADO
            reserva.precio_abonado = actividad.precio_turno
            reserva.save(update_fields=["estado", "estado_pago", "precio_abonado"])

        asistencia = services.obtener_o_crear_asistencia(reserva)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== SEED DE ASISTENCIA COMPLETADO ==="))
        self.stdout.write(self.style.SUCCESS(f"Cliente  -> {CLIENTE_EMAIL}  /  {CLIENTE_PASSWORD}"))
        self.stdout.write(self.style.SUCCESS(f"Empleado -> {EMPLEADO_EMAIL} /  {EMPLEADO_PASSWORD}"))
        self.stdout.write("")
        self.stdout.write(f"Actividad : {actividad.get_nombre_display()}")
        self.stdout.write(f"Turno     : {hoy.strftime('%d/%m/%Y')} a las {hora:02d}:00 (HOY)")
        self.stdout.write(f"Reserva   : id={reserva.pk} (confirmada, pagada por completo)")
        self.stdout.write(self.style.HTTP_INFO(
            f"QR (cliente) : /asistencia/reserva/{reserva.pk}/qr/"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"Marcar (empleado): /asistencia/marcar/{asistencia.codigo}/"
        ))
        self.stdout.write("")
        self.stdout.write(
            "Probá: entrá como cliente y abrí 'Ver QR' en Mis reservas; "
            "luego, como empleado, escaneá o abrí la URL de marcado."
        )

    # ------------------------------------------------------------------
    def _crear_usuario(self, email, password, nombre, apellido, doc, rol, *, staff):
        usuario = Usuario.objects.filter(email=email).first()
        if usuario:
            self.stdout.write(self.style.WARNING(f"Usuario '{email}' ya existía. Se reutiliza."))
            return usuario
        usuario = Usuario.objects.create_user(
            email=email, nombre=nombre, apellido=apellido,
            nro_documento=doc, fecha_nacimiento=date(1995, 6, 15),
            password=password, rol=rol, is_staff=staff,
        )
        self.stdout.write(self.style.SUCCESS(f"+ Usuario creado: {email} ({rol})"))
        return usuario

    def _reset(self):
        emails = [CLIENTE_EMAIL, EMPLEADO_EMAIL]
        # Borrar reservas/turnos asociados al cliente de prueba primero
        Reserva.objects.filter(usuario__email=CLIENTE_EMAIL).delete()
        n = Usuario.objects.filter(email__in=emails).count()
        Usuario.objects.filter(email__in=emails).delete()
        if n:
            self.stdout.write(self.style.WARNING(f"Reset: se eliminaron {n} usuarios de prueba y sus reservas."))
