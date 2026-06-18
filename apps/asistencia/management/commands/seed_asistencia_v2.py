"""
Seed para testear los cambios recientes de asistencia:

  1. Regenerar QR          -> el cliente puede invalidar su QR y generar uno nuevo.
  2. Confirmación por DNI  -> el empleado ve la pantalla de confirmación antes de marcar.
  3. DNI en resultado      -> al finalizar el marcado se muestra el DNI del cliente.
  4. Botón contextual      -> "Registrar otro cliente" si vino por DNI, "Escanear otro QR" si vino por QR.

Crea (idempotente por documento):
  - 1 empleado
  - 2 clientes con reserva pagada para un turno EN CURSO (dentro de la ventana de asistencia ahora mismo)
  - Los objetos Asistencia pre-creados para que las URLs de QR funcionen de inmediato

Uso:
    python manage.py seed_asistencia_v2
    python manage.py seed_asistencia_v2 --password MiClave123
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.asistencia import services
from apps.turnos.models import Reserva, Turno

DOC_EMPLEADO   = "99000001"
DOC_CLIENTE_A  = "99000010"
DOC_CLIENTE_B  = "99000011"
PASSWORD_DEFECTO = "Prueba360!"


class Command(BaseCommand):
    help = "Seed para testear los cambios recientes de asistencia (regenerar QR, confirmación por DNI, etc.)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=PASSWORD_DEFECTO)

    def handle(self, *args, **options):
        password = options["password"]

        # Idempotencia
        Usuario.objects.filter(nro_documento__in=[DOC_EMPLEADO, DOC_CLIENTE_A, DOC_CLIENTE_B]).delete()

        empleado = Usuario.objects.create_user(
            email="v2.empleado@club360.test", nombre="Ernesto", apellido="Empleado",
            nro_documento=DOC_EMPLEADO, fecha_nacimiento=date(1988, 4, 10),
            password=password, rol=Roles.EMPLOYEE, is_staff=True,
        )
        cliente_a = Usuario.objects.create_user(
            email="v2.clienteA@club360.test", nombre="Ana", apellido="ClienteA",
            nro_documento=DOC_CLIENTE_A, fecha_nacimiento=date(1995, 7, 20),
            password=password, rol=Roles.USER,
        )
        cliente_b = Usuario.objects.create_user(
            email="v2.clienteB@club360.test", nombre="Bruno", apellido="ClienteB",
            nro_documento=DOC_CLIENTE_B, fecha_nacimiento=date(1993, 11, 3),
            password=password, rol=Roles.USER,
        )

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.BASKET, defaults={"cupos": 20, "precio_turno": 6000}
        )

        hoy  = timezone.localdate()
        hora = timezone.localtime().hour  # ahora mismo -> dentro de la ventana

        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=hoy, hora=hora, defaults={"cupos": 20}
        )

        reserva_a = self._reserva_paga(cliente_a, turno, actividad.precio_turno)
        reserva_b = self._reserva_paga(cliente_b, turno, actividad.precio_turno)

        asistencia_a = services.obtener_o_crear_asistencia(reserva_a)
        asistencia_b = services.obtener_o_crear_asistencia(reserva_b)

        # ── Reporte ───────────────────────────────────────────────────────────
        sep = "-" * 55
        ok  = self.style.SUCCESS
        inf = self.style.HTTP_INFO

        self.stdout.write(ok(f"\n{'='*55}"))
        self.stdout.write(ok(" SEED ASISTENCIA V2 - cambios recientes"))
        self.stdout.write(ok(f"{'='*55}\n"))

        self.stdout.write(f"Contraseña de todos los usuarios: {password}\n")
        self.stdout.write(f"  Empleado  : {empleado.email}  (DNI {DOC_EMPLEADO})")
        self.stdout.write(f"  Cliente A : {cliente_a.email}  (DNI {DOC_CLIENTE_A})")
        self.stdout.write(f"  Cliente B : {cliente_b.email}  (DNI {DOC_CLIENTE_B})")
        self.stdout.write(f"\nTurno: {actividad.get_nombre_display()} — hoy {hoy:%d/%m/%Y} {hora:02d}:00 (EN CURSO)\n")

        self.stdout.write(sep)
        self.stdout.write(" TEST 1 — Regenerar QR")
        self.stdout.write(sep)
        self.stdout.write("  1. Iniciá sesión como Cliente A.")
        self.stdout.write(inf(f"     /asistencia/reserva/{reserva_a.pk}/qr/"))
        self.stdout.write("  2. Vas a ver el botón 'Regenerar QR' debajo del código.")
        self.stdout.write("  3. Hace clic -> la URL de marcado cambia (nuevo UUID).")
        self.stdout.write("  4. El QR anterior ya no sirve.\n")

        self.stdout.write(sep)
        self.stdout.write(" TEST 2 — Marcado por DNI con pantalla de confirmación")
        self.stdout.write(sep)
        self.stdout.write("  1. Iniciá sesión como Empleado.")
        self.stdout.write(inf("     /asistencia/marcar-dni/"))
        self.stdout.write(f"  2. Ingresá DNI {DOC_CLIENTE_B} -> aparece 'Bruno ClienteB'.")
        self.stdout.write("  3. Hacé clic en 'Marcar presente'.")
        self.stdout.write("  4. Debés ver la pantalla de CONFIRMACIÓN (nombre, actividad,")
        self.stdout.write("     fecha, horario, estado de pago) antes de confirmar.")
        self.stdout.write("  5. Confirmá -> resultado de marcado.\n")

        self.stdout.write(sep)
        self.stdout.write(" TEST 3 — DNI visible en resultado")
        self.stdout.write(sep)
        self.stdout.write("  (continuación del TEST 2)")
        self.stdout.write(f"  En la pantalla de resultado debe aparecer el DNI {DOC_CLIENTE_B}.")
        self.stdout.write("  Verificá que la fila 'DNI' esté en el bloque de datos del cliente.\n")

        self.stdout.write(sep)
        self.stdout.write(" TEST 4 — Botón contextual en resultado")
        self.stdout.write(sep)
        self.stdout.write("  Flujo por DNI  -> botón debe decir 'Registrar otro cliente'")
        self.stdout.write(inf("                  y llevar a /asistencia/marcar-dni/"))
        self.stdout.write("  Flujo por QR   -> botón debe decir 'Escanear otro QR'")
        self.stdout.write(inf(f"                  probalo abriendo /asistencia/marcar/{asistencia_a.codigo}/"))
        self.stdout.write("                  (GET -> confirmación -> POST)\n")

        self.stdout.write(ok(f"{'='*55}\n"))

    def _reserva_paga(self, usuario, turno, precio) -> Reserva:
        r, _ = Reserva.objects.get_or_create(
            usuario=usuario, turno=turno,
            defaults={
                "estado": Reserva.Estado.CONFIRMADA,
                "estado_pago": Reserva.EstadoPago.PAGADO,
                "tipo_reserva": Reserva.TipoReserva.INDIVIDUAL,
                "precio_abonado": precio,
            },
        )
        return r
