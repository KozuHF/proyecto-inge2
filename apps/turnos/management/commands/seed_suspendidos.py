"""
Seed de usuarios de prueba para casos de suspensión y asistencia.

Uso:
    python manage.py seed_suspendidos

Credenciales generadas:
    No abonado suspendido            -> suspendido_no_abonado@test.com  /  User123!
    Abonado suspendido               -> suspendido_abonado@test.com     /  User123!
    No abonado señado                -> senado_no_abonado@test.com      /  User123!
    No abonado con reserva cancelada -> cancelada_no_abonado@test.com   /  User123!
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.asistencia.models import Asistencia
from apps.turnos.models import Reserva, SuspensionAbonado, Turno

USER_PASSWORD = "User123!"

NO_ABONADO_EMAIL = "suspendido_no_abonado@test.com"
ABONADO_EMAIL = "suspendido_abonado@test.com"
SENADO_EMAIL = "senado_no_abonado@test.com"
CANCELADA_EMAIL = "cancelada_no_abonado@test.com"


class Command(BaseCommand):
    help = "Crea usuarios de prueba para casos de suspensión y asistencia."

    @transaction.atomic
    def handle(self, *args, **options):
        no_abonado = self._crear_no_abonado_suspendido()
        abonado = self._crear_abonado_suspendido()
        senado, asistencia_senado = self._crear_no_abonado_senado()
        cancelada, asistencia_cancelada = self._crear_no_abonado_cancelada()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== SEED COMPLETADO ==="))
        self.stdout.write(self.style.SUCCESS(
            f"No abonado suspendido -> {no_abonado.email}  /  {USER_PASSWORD}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Abonado suspendido    -> {abonado.email}  /  {USER_PASSWORD}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"No abonado señado     -> {senado.email}  /  {USER_PASSWORD}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"  URL para escanear (logueado como empleado/admin) -> "
            f"/asistencia/marcar/{asistencia_senado.codigo}/"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"No abonado con reserva cancelada -> {cancelada.email}  /  {USER_PASSWORD}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"  URL para escanear (logueado como empleado/admin) -> "
            f"/asistencia/marcar/{asistencia_cancelada.codigo}/"
        ))

    def _crear_no_abonado_suspendido(self) -> Usuario:
        usuario, creado = Usuario.objects.get_or_create(
            email=NO_ABONADO_EMAIL,
            defaults=dict(
                nombre="Nora",
                apellido="Suspendida",
                nro_documento="20000001",
                fecha_nacimiento=date(1995, 6, 15),
                rol=Roles.USER,
            ),
        )
        if creado:
            usuario.set_password(USER_PASSWORD)

        usuario.suspendido = True
        usuario.monto_adeudado_suspension = Decimal("5000.00")
        usuario.save(update_fields=["suspendido", "monto_adeudado_suspension", "password"])

        estado = "creado" if creado else "ya existía, se actualizó"
        self.stdout.write(f"  + No abonado suspendido {estado}: {usuario.email}")
        return usuario

    def _crear_abonado_suspendido(self) -> Usuario:
        usuario, creado = Usuario.objects.get_or_create(
            email=ABONADO_EMAIL,
            defaults=dict(
                nombre="Aldo",
                apellido="Abonado",
                nro_documento="20000002",
                fecha_nacimiento=date(1995, 6, 15),
                rol=Roles.USER,
            ),
        )
        if creado:
            usuario.set_password(USER_PASSWORD)
            usuario.save()

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )

        SuspensionAbonado.objects.get_or_create(
            usuario=usuario, actividad=actividad, activa=True,
            defaults=dict(
                motivo=SuspensionAbonado.Motivo.PLAZO_VENCIDO,
                monto_adeudado=Decimal("10500.00"),
            ),
        )

        estado = "creado" if creado else "ya existía"
        self.stdout.write(f"  + Abonado suspendido {estado}: {usuario.email} ({actividad})")
        return usuario

    def _crear_no_abonado_senado(self) -> tuple[Usuario, Asistencia]:
        usuario, creado = Usuario.objects.get_or_create(
            email=SENADO_EMAIL,
            defaults=dict(
                nombre="Sonia",
                apellido="Senada",
                nro_documento="20000003",
                fecha_nacimiento=date(1995, 6, 15),
                rol=Roles.USER,
            ),
        )
        if creado:
            usuario.set_password(USER_PASSWORD)
            usuario.save()

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )

        # Turno "ahora" para que quede dentro de la ventana de asistencia.
        ahora = timezone.localtime()
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=ahora.date(), hora=ahora.hour,
            defaults={"cupos": 5},
        )

        reserva, _ = Reserva.objects.update_or_create(
            usuario=usuario, turno=turno,
            defaults=dict(
                estado=Reserva.Estado.CONFIRMADA,
                estado_pago=Reserva.EstadoPago.SENADO,
                tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
                precio_abonado=Decimal("2500.00"),
            ),
        )

        asistencia, _ = Asistencia.objects.get_or_create(reserva=reserva)

        self.stdout.write(
            f"  + No abonado señado: {usuario.email} (turno {turno.fecha} {turno.hora}:00, "
            f"{actividad})"
        )
        return usuario, asistencia

    def _crear_no_abonado_cancelada(self) -> tuple[Usuario, Asistencia]:
        usuario, creado = Usuario.objects.get_or_create(
            email=CANCELADA_EMAIL,
            defaults=dict(
                nombre="Carla",
                apellido="Cancelada",
                nro_documento="20000004",
                fecha_nacimiento=date(1995, 6, 15),
                rol=Roles.USER,
            ),
        )
        if creado:
            usuario.set_password(USER_PASSWORD)
            usuario.save()

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )

        # Turno "ahora" para que la clase esté vigente al momento de escanear.
        ahora = timezone.localtime()
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=ahora.date(), hora=ahora.hour,
            defaults={"cupos": 5},
        )

        reserva, _ = Reserva.objects.update_or_create(
            usuario=usuario, turno=turno,
            defaults=dict(
                estado=Reserva.Estado.CONFIRMADA,
                estado_pago=Reserva.EstadoPago.PAGADO,
                tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
                precio_abonado=Decimal("5000.00"),
            ),
        )

        asistencia, _ = Asistencia.objects.get_or_create(reserva=reserva)

        # El QR ya existía (se generó con la reserva confirmada); ahora se cancela.
        reserva.estado = Reserva.Estado.CANCELADA
        reserva.save(update_fields=["estado"])

        self.stdout.write(
            f"  + No abonado con reserva cancelada: {usuario.email} "
            f"(turno {turno.fecha} {turno.hora}:00, {actividad})"
        )
        return usuario, asistencia
