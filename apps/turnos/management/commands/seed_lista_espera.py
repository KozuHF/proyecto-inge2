"""
Crea entidades de prueba para la funcionalidad de LISTA DE ESPERA.

Arma dos escenarios para probar a mano:

A) Anotarse en lista de espera: un turno lleno con su HorarioDisponible, para que
   un cliente "explorador" entre por el wizard de reserva, elija ese turno y se
   anote en la lista de espera (sin cargo).

B) Responder una invitación: un turno lleno con un titular confirmado y un cliente
   en espera; se cancela al titular, lo que dispara la invitación al de la lista.
   El cliente invitado puede entrar y aceptar (y pagar) o rechazar.

Es idempotente: borra los datos de prueba previos (por documento) y los recrea.

Uso:
    python manage.py seed_lista_espera
    python manage.py seed_lista_espera --password MiClave123
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.turnos.models import (
    HorarioDisponible, Reserva, Turno, _validar_dia_habil,
)

# Documentos reservados para los datos de prueba (se borran y recrean).
DOC_TITULAR_A = "77000001"
DOC_EXPLORADOR = "77000002"
DOC_TITULAR_B = "77000003"
DOC_INVITADO_B = "77000004"
PASSWORD_DEFECTO = "Prueba360!"
HORA = 19  # hora válida (8-21) para ambos turnos


class Command(BaseCommand):
    help = "Crea datos de prueba para la lista de espera de turnos."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=PASSWORD_DEFECTO)

    def handle(self, *args, **options):
        password = options["password"]
        docs = [DOC_TITULAR_A, DOC_EXPLORADOR, DOC_TITULAR_B, DOC_INVITADO_B]
        Usuario.objects.filter(nro_documento__in=docs).delete()

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.VOLEY, defaults={"cupos": 10, "precio_turno": 6000}
        )

        fecha_a = self._proxima_fecha_habil(desde=timezone.localdate() + timedelta(days=1))
        fecha_b = self._proxima_fecha_habil(desde=fecha_a + timedelta(days=1))
        dia_semana = fecha_a.weekday()

        # Idempotencia: borrar turnos de prueba de corridas anteriores.
        Turno.objects.filter(
            actividad=actividad, fecha__in=[fecha_a, fecha_b], hora=HORA
        ).delete()

        # HorarioDisponible para que el wizard ofrezca esta hora ese día.
        HorarioDisponible.objects.update_or_create(
            actividad=actividad, dia_semana=fecha_a.weekday(), hora=HORA,
            defaults={"activo": True, "cupos": 1, "precio": 6000},
        )
        if fecha_b.weekday() != dia_semana:
            HorarioDisponible.objects.update_or_create(
                actividad=actividad, dia_semana=fecha_b.weekday(), hora=HORA,
                defaults={"activo": True, "cupos": 1, "precio": 6000},
            )

        # Usuarios. Se usan direcciones plus-addressed sobre una misma casilla real
        # para poder verificar que los mails (invitación de cupo, comprobante de
        # pago) lleguen de verdad.
        usuarios = {}
        for doc, plus, nombre, apellido in [
            (DOC_TITULAR_A, "titularA", "Tomás", "TitularA"),
            (DOC_EXPLORADOR, "explorador", "Elena", "Exploradora"),
            (DOC_TITULAR_B, "titularB", "Bruno", "TitularB"),
            (DOC_INVITADO_B, "invitadoB", "Ivo", "Invitado"),
        ]:
            usuarios[doc] = Usuario.objects.create_user(
                email=f"ivannociti212+{plus}@gmail.com", nombre=nombre, apellido=apellido,
                nro_documento=doc, fecha_nacimiento=date(1990, 1, 1),
                password=password, rol=Roles.USER,
            )

        # Escenario A: turno lleno (cupos=1) para que el explorador se anote en espera.
        turno_a = Turno.objects.create(actividad=actividad, fecha=fecha_a, hora=HORA, cupos=1)
        self._confirmada(usuarios[DOC_TITULAR_A], turno_a)

        # Escenario B: turno lleno con un cliente en espera; se cancela al titular
        # para disparar la invitación.
        turno_b = Turno.objects.create(actividad=actividad, fecha=fecha_b, hora=HORA, cupos=1)
        titular_b_reserva = self._confirmada(usuarios[DOC_TITULAR_B], turno_b)
        Reserva.objects.create(
            usuario=usuarios[DOC_INVITADO_B], turno=turno_b,
            estado=Reserva.Estado.EN_ESPERA, tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
        )
        titular_b_reserva.cancelar()  # libera el cupo -> invita al de la lista

        self._reporte(usuarios, fecha_a, fecha_b, password)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _proxima_fecha_habil(self, desde: date) -> date:
        f = desde
        for _ in range(30):
            try:
                _validar_dia_habil(f)
                return f
            except Exception:
                f += timedelta(days=1)
        return desde

    def _confirmada(self, usuario, turno) -> Reserva:
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.PAGADO,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
            precio_abonado=turno.precio_efectivo,
        )

    def _reporte(self, usuarios, fecha_a, fecha_b, password):
        inv = usuarios[DOC_INVITADO_B]
        invitacion = getattr(inv.reservas.first(), "invitacion", None)
        self.stdout.write(self.style.SUCCESS("Datos de prueba de lista de espera creados.\n"))
        self.stdout.write(f"Contraseña de todos los usuarios: {password}\n")

        self.stdout.write("ESCENARIO A — Anotarse en lista de espera (sin cargo):")
        self.stdout.write(f"  Iniciá sesión como: {usuarios[DOC_EXPLORADOR].email}")
        self.stdout.write(
            f"  Reservá Vóley el {fecha_a.strftime('%d/%m/%Y')} a las {HORA:02d}:00 "
            f"(está completo) -> te ofrece anotarte en la lista de espera.\n"
        )

        self.stdout.write("ESCENARIO B — Responder una invitación de cupo:")
        self.stdout.write(f"  Iniciá sesión como: {inv.email}")
        self.stdout.write(
            f"  Vóley el {fecha_b.strftime('%d/%m/%Y')} a las {HORA:02d}:00. "
            "Se liberó un cupo y tenés una invitación pendiente."
        )
        self.stdout.write("  Andá a Mis reservas -> 'Responder invitación' (contador en vivo).")
        if invitacion is not None:
            self.stdout.write(f"  URL directa: /turnos/invitacion/{invitacion.token}/")
        self.stdout.write(
            "  Podés 'Aceptar y pagar' (tarjeta demo: 16 dígitos cualquiera, "
            "venc. futuro, CVV 123) o 'Rechazar'."
        )
