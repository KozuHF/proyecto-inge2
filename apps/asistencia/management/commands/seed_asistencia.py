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
        parser.add_argument("--abono-vencido", action="store_true",
                            help="Además crea un abono mensual impago con el plazo ya vencido "
                                 "(para probar que el QR se bloquea).")

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

        # ── Escenario 2: abono mensual con pago PENDIENTE ─────────────────
        # El abonado tiene QR desde que reserva (paga hasta el día 10).
        reserva_abono, asistencia_abono = self._crear_abono_pendiente(cliente, hoy, hora)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== SEED DE ASISTENCIA COMPLETADO ==="))
        self.stdout.write(self.style.SUCCESS(f"Cliente  -> {CLIENTE_EMAIL}  /  {CLIENTE_PASSWORD}"))
        self.stdout.write(self.style.SUCCESS(f"Empleado -> {EMPLEADO_EMAIL} /  {EMPLEADO_PASSWORD}"))
        self.stdout.write("")
        self.stdout.write("— Turno individual (pagado por completo) —")
        self.stdout.write(f"Actividad : {actividad.get_nombre_display()}")
        self.stdout.write(f"Turno     : {hoy.strftime('%d/%m/%Y')} a las {hora:02d}:00 (HOY)")
        self.stdout.write(f"Reserva   : id={reserva.pk}")
        self.stdout.write(self.style.HTTP_INFO(
            f"QR (cliente) : /asistencia/reserva/{reserva.pk}/qr/"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"Marcar (empleado): /asistencia/marcar/{asistencia.codigo}/"
        ))
        self.stdout.write("")
        self.stdout.write("— Abono mensual (pago PENDIENTE: QR disponible igual) —")
        self.stdout.write(f"Actividad : {reserva_abono.turno.actividad.get_nombre_display()}")
        self.stdout.write(f"Turno     : {hoy.strftime('%d/%m/%Y')} a las {reserva_abono.turno.hora:02d}:00 (HOY)")
        self.stdout.write(f"Reserva   : id={reserva_abono.pk}")
        self.stdout.write(self.style.HTTP_INFO(
            f"QR (cliente) : /asistencia/reserva/{reserva_abono.pk}/qr/"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"Marcar (empleado): /asistencia/marcar/{asistencia_abono.codigo}/"
        ))
        if options["abono_vencido"]:
            reserva_venc = self._crear_abono_vencido(cliente)
            self.stdout.write("")
            self.stdout.write("— Abono mensual con PLAZO VENCIDO (QR bloqueado) —")
            self.stdout.write(f"Turno     : {reserva_venc.turno.fecha.strftime('%d/%m/%Y')} (mes vencido)")
            self.stdout.write(f"Reserva   : id={reserva_venc.pk}")
            self.stdout.write(self.style.HTTP_INFO(
                f"QR (cliente) : /asistencia/reserva/{reserva_venc.pk}/qr/  ->  debe mostrar 'QR no disponible'"
            ))

        self.stdout.write("")
        self.stdout.write(
            "Probá: entrá como cliente y abrí 'Ver QR' en Mis reservas; "
            "luego, como empleado, escaneá o abrí la URL de marcado."
        )

    def _crear_abono_vencido(self, cliente):
        """
        Abono mensual del mes pasado, con un turno el día 5 (rango 1–10) e impago.
        Como ya pasó el día 10 de ese mes, el plazo está vencido y el QR se bloquea.
        """
        from datetime import date
        from apps.turnos.models import GrupoReservaMensual

        hoy = timezone.localdate()
        mes = hoy.month - 1 or 12
        anio = hoy.year - (1 if hoy.month == 1 else 0)
        fecha = date(anio, mes, 5)  # día 1–10 → aplica el plazo del día 10

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.BASKET, defaults={"cupos": 20, "precio_turno": 5000}
        )
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=fecha, hora=10,
            defaults={"cupos": actividad.cupos},
        )
        grupo, _ = GrupoReservaMensual.objects.get_or_create(
            usuario=cliente, actividad=actividad, dia_semana=fecha.weekday(),
            hora=10, anio=anio, mes=mes, defaults={"regla_cobro": "primera_quincena"},
        )
        reserva, creada = Reserva.objects.get_or_create(
            usuario=cliente, turno=turno,
            defaults={
                "estado": Reserva.Estado.CONFIRMADA,
                "estado_pago": Reserva.EstadoPago.PENDIENTE,
                "tipo_reserva": Reserva.TipoReserva.VARIOS,
                "grupo_mensual": grupo,
            },
        )
        if not creada:
            reserva.estado = Reserva.Estado.CONFIRMADA
            reserva.estado_pago = Reserva.EstadoPago.PENDIENTE
            reserva.tipo_reserva = Reserva.TipoReserva.VARIOS
            reserva.grupo_mensual = grupo
            reserva.save(update_fields=["estado", "estado_pago", "tipo_reserva", "grupo_mensual"])
        return reserva

    def _crear_abono_pendiente(self, cliente, hoy, hora):
        """Reserva de abono mensual impaga, con turno HOY (otra actividad)."""
        from apps.turnos.abono_mensual import clasificar_regla_abono
        from apps.turnos.models import GrupoReservaMensual

        actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.VOLEY, defaults={"cupos": 20, "precio_turno": 5000}
        )
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=hoy, hora=hora,
            defaults={"cupos": actividad.cupos},
        )
        grupo, _ = GrupoReservaMensual.objects.get_or_create(
            usuario=cliente,
            actividad=actividad,
            dia_semana=hoy.weekday(),
            hora=hora,
            anio=hoy.year,
            mes=hoy.month,
            defaults={"regla_cobro": clasificar_regla_abono([hoy])},
        )
        reserva, creada = Reserva.objects.get_or_create(
            usuario=cliente, turno=turno,
            defaults={
                "estado": Reserva.Estado.CONFIRMADA,
                "estado_pago": Reserva.EstadoPago.PENDIENTE,
                "tipo_reserva": Reserva.TipoReserva.VARIOS,
                "grupo_mensual": grupo,
            },
        )
        if not creada:
            reserva.estado = Reserva.Estado.CONFIRMADA
            reserva.estado_pago = Reserva.EstadoPago.PENDIENTE
            reserva.tipo_reserva = Reserva.TipoReserva.VARIOS
            reserva.grupo_mensual = grupo
            reserva.save(update_fields=["estado", "estado_pago", "tipo_reserva", "grupo_mensual"])

        asistencia = services.obtener_o_crear_asistencia(reserva)
        return reserva, asistencia

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
