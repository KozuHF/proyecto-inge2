"""
Seed del Escenario 1: Registro de cliente no abonado en la lista de espera exitoso.

Crea el turno de Fútbol del 06/07/2026 17hs LLENO (5/5 cupos, todos con
reserva confirmada) y un cliente no abonado sin reserva ni lugar en la lista
de espera para esa clase, listo para probar "Anotarme en lista de espera".

Uso:
    python manage.py seed_escenario1_lista_espera

Credenciales generadas:
    Cliente -> escenario1_cliente@test.com  /  User123!
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.turnos.models import HorarioDisponible, Reserva, Turno

CLIENTE_EMAIL = "escenario1_cliente@test.com"
USER_PASSWORD = "User123!"

FECHA_TURNO = date(2026, 7, 6)
HORA_TURNO = 17
CUPOS = 5


class Command(BaseCommand):
    help = "Crea las condiciones del Escenario 1 (lista de espera, no abonado)."

    @transaction.atomic
    def handle(self, *args, **options):
        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": CUPOS, "precio_turno": 5000},
        )

        HorarioDisponible.objects.update_or_create(
            actividad=actividad, dia_semana=FECHA_TURNO.weekday(), hora=HORA_TURNO,
            defaults={"activo": True, "cupos": CUPOS, "precio": actividad.precio_turno},
        )

        turno, _ = Turno.objects.update_or_create(
            actividad=actividad, fecha=FECHA_TURNO, hora=HORA_TURNO,
            defaults={"cupos": CUPOS},
        )

        # Limpiar reservas previas de prueba en este turno para dejarlo en un
        # estado predecible (5 confirmadas, cupo lleno).
        Reserva.objects.filter(turno=turno).delete()

        for i in range(1, CUPOS + 1):
            ocupante, creado = Usuario.objects.get_or_create(
                email=f"escenario1_ocupante{i}@test.com",
                defaults=dict(
                    nombre=f"Ocupante{i}",
                    apellido="Fútbol",
                    nro_documento=f"3000000{i}",
                    fecha_nacimiento=date(1995, 6, 15),
                    rol=Roles.USER,
                ),
            )
            if creado:
                ocupante.set_password(USER_PASSWORD)
                ocupante.save()

            Reserva.objects.create(
                usuario=ocupante, turno=turno,
                estado=Reserva.Estado.CONFIRMADA,
                estado_pago=Reserva.EstadoPago.PAGADO,
                tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
                precio_abonado=Decimal("5000.00"),
            )

        cliente, creado = Usuario.objects.get_or_create(
            email=CLIENTE_EMAIL,
            defaults=dict(
                nombre="Camila",
                apellido="Espera",
                nro_documento="30000099",
                fecha_nacimiento=date(1995, 6, 15),
                rol=Roles.USER,
            ),
        )
        if creado:
            cliente.set_password(USER_PASSWORD)
            cliente.save()

        # El cliente no debe tener reserva ni lugar en lista de espera para este turno.
        Reserva.objects.filter(usuario=cliente, turno=turno).delete()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== ESCENARIO 1 LISTO ==="))
        self.stdout.write(self.style.SUCCESS(
            f"Turno: Fútbol {FECHA_TURNO:%d/%m/%Y} {HORA_TURNO}:00-{HORA_TURNO + 1}:00 "
            f"— {turno.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count()}/{CUPOS} cupos (LLENO)"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Cliente (no abonado, sin reserva ni lista de espera) -> {cliente.email}  /  {USER_PASSWORD}"
        ))
        self.stdout.write(
            "Pasos: login -> Reservar -> Turno único -> Fútbol -> "
            f"{FECHA_TURNO:%d/%m/%Y} -> {HORA_TURNO}hs (LLENO) -> Siguiente -> "
            "'Anotarme en lista de espera'."
        )
