"""
Seed unificado para la PRE-DEMO de las 7 Historias de Usuario.

Prepara, de forma idempotente, todo el estado necesario para mostrar en vivo:

  HU1 - Ver historial de asistencias       (cliente)
  HU2 - Registro manual de asistencia x DNI (empleado)
  HU3 - Escanear QR                         (empleado)
  HU4 - Generar QR por turno                (cliente)
  HU5 - Unirse a la lista de espera         (cliente)
  HU6 - Notificar a administradores         (sistema)
  HU7 - Ofrecer turno automaticamente       (sistema)

Detalle clave: el aviso a admins (HU6) se dispara cuando el TOTAL de reservas
EN_ESPERA del sistema llega a EXACTAMENTE 10 (UMBRAL_AVISO_LISTA_ESPERA). El seed
deja el sistema en 9, asi la anotacion en vivo de HU5 dispara HU6.

Las clases de asistencia en vivo (HU2/HU3) usan la fecha de hoy y la hora de
exposicion (--hora, default = hora actual) para caer dentro de la ventana de
asistencia. Los mails (HU6/HU7) salen por SMTP real a ivannociti212+<rol>@gmail.com.

Uso:
    python manage.py seed_predemo                 # hora actual
    python manage.py seed_predemo --hora 16       # fija la hora de las clases en vivo
    python manage.py seed_predemo --password X     # cambia la contrasena comun
"""
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.asistencia import services as asistencia_services
from apps.asistencia.models import Asistencia
from apps.turnos.models import (
    GrupoReservaMensual,
    InvitacionCupo,
    Reserva,
    Turno,
    _validar_dia_habil,
)

PASSWORD_DEFECTO = "Prueba360!"
TOTAL_ESPERA_OBJETIVO = 9  # para que la anotacion en vivo de HU5 lleve a 10 (umbral)

# DNIs reservados para los datos de prueba (se borran y recrean).
DNI_PROTAGONISTA = "90000100"
DNI_EMPLEADO     = "90000101"
DNI_ADMIN        = "90000102"
DNI_ESCANEO      = "90000103"
# Clientes de HU2 con los DNIs (sin puntos) que figuran en la HU.
DNI_HU2_OK       = "11222333"
DNI_HU2_SINCLASE = "11222334"
DNI_HU2_VENCIDA  = "22333444"
# HU7
DNI_TITULAR_1    = "90000111"
DNI_TITULAR_2    = "90000112"
DNI_TITULAR_5    = "90000110"
DNI_C_ESC1       = "90000120"  # no abonado, oferta directa
DNI_C_ESC2       = "90000121"  # abonado, oferta directa
DNI_C_ESC3A      = "90000122"  # no abonado, 1ro (invitacion vencida)
DNI_C_ESC3B      = "90000123"  # no abonado, 2do (recibe tras vencimiento)
DNI_C_ESC4A      = "90000124"  # abonado, 1ro (invitacion vencida)
DNI_C_ESC4B      = "90000125"  # abonado, 2do (recibe tras vencimiento)
DNI_RELLENO      = [f"9000013{i}" for i in range(8)]  # 90000130..90000137

TODOS_LOS_DNI = [
    DNI_PROTAGONISTA, DNI_EMPLEADO, DNI_ADMIN, DNI_ESCANEO,
    DNI_HU2_OK, DNI_HU2_SINCLASE, DNI_HU2_VENCIDA,
    DNI_TITULAR_1, DNI_TITULAR_2, DNI_TITULAR_5,
    DNI_C_ESC1, DNI_C_ESC2, DNI_C_ESC3A, DNI_C_ESC3B, DNI_C_ESC4A, DNI_C_ESC4B,
] + DNI_RELLENO


class Command(BaseCommand):
    help = "Prepara los datos para la pre-demo de las 7 Historias de Usuario."

    def add_arguments(self, parser):
        parser.add_argument("--hora", type=int, default=None,
                            help="Hora (8-21) de las clases de asistencia en vivo. Default: hora actual.")
        parser.add_argument("--password", default=PASSWORD_DEFECTO)

    @transaction.atomic
    def handle(self, *args, **options):
        self.password = options["password"]

        ahora = timezone.localtime()
        H = options["hora"] if options["hora"] is not None else ahora.hour
        H = max(9, min(H, 20))  # acotar a un rango razonable

        hoy = timezone.localdate()
        ayer = hoy - timedelta(days=1)
        # Hora "ya vencida" del dia de hoy (su ventana de asistencia ya cerro).
        hora_vencida = H - 3 if (H - 3) >= 8 else 8
        f0, f1 = self._proximas_fechas_habiles(hoy, 2)

        self._reset()

        # Actividades (se crean si no existen).
        voley  = self._actividad(Actividad.Nombre.VOLEY, 8000)
        futbol = self._actividad(Actividad.Nombre.FUTBOL, 9000)
        basket = self._actividad(Actividad.Nombre.BASKET, 8500)
        paddle = self._actividad(Actividad.Nombre.PADDLE, 12000)

        # ── Usuarios ──────────────────────────────────────────────────────────
        protagonista = self._usuario(DNI_PROTAGONISTA, "cliente", "Caro", "Cliente", Roles.USER)
        empleado     = self._usuario(DNI_EMPLEADO, "empleado", "Emi", "Empleado", Roles.EMPLOYEE, staff=True)
        self._usuario(DNI_ADMIN, "admin", "Ada", "Admin", Roles.ADMIN, staff=True)
        escaneo      = self._usuario(DNI_ESCANEO, "escaneo", "Esteban", "Escaneo", Roles.USER)
        cli_ok       = self._usuario(DNI_HU2_OK, "dni1", "Dario", "DniOk", Roles.USER)
        self._usuario(DNI_HU2_SINCLASE, "dni2", "Dina", "DniSinClase", Roles.USER)
        cli_venc     = self._usuario(DNI_HU2_VENCIDA, "dni3", "Diego", "DniVencida", Roles.USER)

        # ── HU4: Generar QR (Voley f0 17h, sin Asistencia previa) ──────────────
        turno_qr = self._turno(voley, f0, 17, cupos=20)
        reserva_qr = self._reserva_paga(protagonista, turno_qr)
        # NO se crea Asistencia: el cliente la genera al presionar "Ver QR".

        # ── HU1: Historial (ayer, ventana cerrada, presente y ausente) ─────────
        r_pres = self._reserva_paga(protagonista, self._turno(voley, ayer, 12, cupos=20))
        self._asistencia(r_pres, presente=True, empleado=empleado)
        r_aus = self._reserva_paga(protagonista, self._turno(futbol, ayer, 13, cupos=20))
        self._asistencia(r_aus, presente=False)

        # ── HU3: Escanear QR (hoy, hora de exposicion) ─────────────────────────
        # (a) en ventana, sin marcar -> escaneo exitoso
        r_e_ok = self._reserva_paga(escaneo, self._turno(paddle, hoy, H, cupos=20))
        a_e_ok = self._asistencia(r_e_ok, presente=False)
        # (b) fuera de ventana (hora ya vencida hoy) -> "horario incorrecto"
        r_e_fv = self._reserva_paga(escaneo, self._turno(futbol, hoy, hora_vencida, cupos=20))
        a_e_fv = self._asistencia(r_e_fv, presente=False)
        # (c) en ventana, ya marcada -> "ya utilizado"
        r_e_ya = self._reserva_paga(escaneo, self._turno(basket, hoy, H, cupos=20))
        a_e_ya = self._asistencia(r_e_ya, presente=True, empleado=empleado)

        # ── HU2: Marcado por DNI (hoy) ─────────────────────────────────────────
        # (ok) cliente en curso -> marcable
        r_d_ok = self._reserva_paga(cli_ok, self._turno(paddle, hoy, H, cupos=20))
        self._asistencia(r_d_ok, presente=False)
        # (vencida) cliente con clase ya finalizada hoy -> no marcable
        r_d_fv = self._reserva_paga(cli_venc, self._turno(futbol, hoy, hora_vencida, cupos=20))
        self._asistencia(r_d_fv, presente=False)
        # (sin clase) DNI_HU2_SINCLASE no tiene reservas.

        # ── HU5: Lista de espera (Futbol f0 17h LLENO; protagonista se anota en vivo)
        titular_5 = self._usuario(DNI_TITULAR_5, "titular5", "Tomas", "TitularFutbol", Roles.USER)
        turno_hu5 = self._turno(futbol, f0, 17, cupos=1)
        self._reserva_paga(titular_5, turno_hu5)  # llena el turno

        # ── HU7: Ofrecer turno ─────────────────────────────────────────────────
        titular_1 = self._usuario(DNI_TITULAR_1, "titular1", "Tania", "TitularVoley", Roles.USER)
        titular_2 = self._usuario(DNI_TITULAR_2, "titular2", "Teo", "TitularPadel", Roles.USER)
        c_esc1 = self._usuario(DNI_C_ESC1, "espera1", "Nico", "NoAbonado1", Roles.USER)
        c_esc2 = self._usuario(DNI_C_ESC2, "espera2", "Abel", "Abonado2", Roles.USER)
        c_esc3a = self._usuario(DNI_C_ESC3A, "espera3a", "Pri", "NoAbonado3a", Roles.USER)
        c_esc3b = self._usuario(DNI_C_ESC3B, "espera3b", "Seo", "NoAbonado3b", Roles.USER)
        c_esc4a = self._usuario(DNI_C_ESC4A, "espera4a", "Ali", "Abonado4a", Roles.USER)
        c_esc4b = self._usuario(DNI_C_ESC4B, "espera4b", "Bru", "Abonado4b", Roles.USER)

        # Esc1: Voley f0 18h LLENO, 1 no-abonado en espera (lista de abonados vacia)
        t_esc1 = self._turno(voley, f0, 18, cupos=1)
        self._reserva_paga(titular_1, t_esc1)
        self._reserva_espera(c_esc1, t_esc1)

        # Esc2: Padel f0 17h LLENO, 1 abonado en espera
        t_esc2 = self._turno(paddle, f0, 17, cupos=1)
        self._reserva_paga(titular_2, t_esc2)
        r_ab2 = self._reserva_espera(c_esc2, t_esc2, abono=True)
        self._grupo_abono(c_esc2, paddle, t_esc2, r_ab2)

        # Esc3: Voley f1 17h, 1ro INVITADO (vencido) + 2do EN_ESPERA (no abonados)
        t_esc3 = self._turno(voley, f1, 17, cupos=1)
        r_inv3 = self._reserva_invitado(c_esc3a, t_esc3)
        self._invitacion_vencida(r_inv3)
        self._reserva_espera(c_esc3b, t_esc3)

        # Esc4: Padel f1 17h, 1ro abonado INVITADO (vencido) + 2do abonado EN_ESPERA
        t_esc4 = self._turno(paddle, f1, 17, cupos=1)
        r_inv4 = self._reserva_invitado(c_esc4a, t_esc4, abono=True)
        self._grupo_abono(c_esc4a, paddle, t_esc4, r_inv4)
        self._invitacion_vencida(r_inv4)
        r_ab4b = self._reserva_espera(c_esc4b, t_esc4, abono=True)
        self._grupo_abono(c_esc4b, paddle, t_esc4, r_ab4b)

        # ── Cuadre del contador global a 9 ─────────────────────────────────────
        faltan = self._cuadrar_espera(basket, f0)

        # ── Reporte ────────────────────────────────────────────────────────────
        self._reporte(
            H=H, hoy=hoy, ayer=ayer, f0=f0, f1=f1, hora_vencida=hora_vencida,
            reserva_qr=reserva_qr, a_e_ok=a_e_ok, a_e_fv=a_e_fv, a_e_ya=a_e_ya,
            escaneo=escaneo, empleado=empleado, protagonista=protagonista,
            titular_5=titular_5, titular_1=titular_1, titular_2=titular_2,
            faltan=faltan,
        )

    # ── Helpers de creacion ────────────────────────────────────────────────────

    def _proximas_fechas_habiles(self, desde: date, n: int) -> list:
        """Devuelve las proximas n fechas habiles (lun-sab, sin feriados) desde manana."""
        fechas, f = [], desde + timedelta(days=1)
        while len(fechas) < n:
            try:
                _validar_dia_habil(f)
                fechas.append(f)
            except Exception:
                pass
            f += timedelta(days=1)
        return fechas

    def _actividad(self, nombre, precio) -> Actividad:
        act, _ = Actividad.objects.get_or_create(
            nombre=nombre, defaults={"cupos": 20, "precio_turno": precio}
        )
        return act

    def _usuario(self, dni, plus, nombre, apellido, rol, *, staff=False) -> Usuario:
        return Usuario.objects.create_user(
            email=f"ivannociti212+{plus}@gmail.com",
            nombre=nombre, apellido=apellido, nro_documento=dni,
            fecha_nacimiento=date(1995, 1, 1), password=self.password,
            rol=rol, is_staff=staff,
        )

    def _turno(self, actividad, fecha, hora, cupos) -> Turno:
        turno, _ = Turno.objects.get_or_create(
            actividad=actividad, fecha=fecha, hora=hora, defaults={"cupos": cupos}
        )
        return turno

    def _reserva_paga(self, usuario, turno) -> Reserva:
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.PAGADO,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
            precio_abonado=turno.precio_efectivo,
            referencia_pago="SEED-PREDEMO",
        )

    def _reserva_espera(self, usuario, turno, *, abono=False) -> Reserva:
        """Crea una reserva EN_ESPERA directo (sin disparar chequear_umbral_admin)."""
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.EN_ESPERA,
            tipo_reserva=Reserva.TipoReserva.VARIOS if abono else Reserva.TipoReserva.INDIVIDUAL,
        )

    def _reserva_invitado(self, usuario, turno, *, abono=False) -> Reserva:
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.INVITADO,
            tipo_reserva=Reserva.TipoReserva.VARIOS if abono else Reserva.TipoReserva.INDIVIDUAL,
        )

    def _invitacion_vencida(self, reserva) -> InvitacionCupo:
        """Invitacion PENDIENTE con vencimiento en el pasado (lista para procesar en vivo)."""
        return InvitacionCupo.objects.create(
            reserva=reserva,
            estado=InvitacionCupo.Estado.PENDIENTE,
            fecha_vencimiento=timezone.now() - timedelta(minutes=5),
        )

    def _grupo_abono(self, usuario, actividad, turno, reserva) -> GrupoReservaMensual:
        """Crea el abono que hace al usuario 'abonado' de la actividad y vincula la reserva."""
        grupo = GrupoReservaMensual.objects.create(
            usuario=usuario, actividad=actividad,
            dia_semana=turno.fecha.weekday(), hora=turno.hora,
            anio=turno.fecha.year, mes=turno.fecha.month,
            regla_cobro="primera_quincena",
        )
        reserva.grupo_mensual = grupo
        reserva.save(update_fields=["grupo_mensual"])
        return grupo

    def _asistencia(self, reserva, *, presente, empleado=None) -> Asistencia:
        asistencia = asistencia_services.obtener_o_crear_asistencia(reserva)
        if presente:
            asistencia.presente = True
            asistencia.fecha_registro = timezone.now()
            asistencia.registrado_por = empleado
            asistencia.save(update_fields=["presente", "fecha_registro", "registrado_por"])
        return asistencia

    def _cuadrar_espera(self, actividad, fecha) -> int:
        """Crea reservas EN_ESPERA de relleno hasta dejar el total global en 9."""
        actuales = Reserva.objects.filter(estado=Reserva.Estado.EN_ESPERA).count()
        faltan = TOTAL_ESPERA_OBJETIVO - actuales
        if faltan <= 0:
            return faltan
        turno_relleno = self._turno(actividad, fecha, 19, cupos=1)
        for i in range(faltan):
            u = self._usuario(DNI_RELLENO[i], f"relleno{i}", f"Rel{i}", "Relleno", Roles.USER)
            self._reserva_espera(u, turno_relleno)
        return faltan

    # ── Idempotencia ────────────────────────────────────────────────────────────

    def _reset(self):
        Usuario.objects.filter(nro_documento__in=TODOS_LOS_DNI).delete()

    # ── Reporte ──────────────────────────────────────────────────────────────────

    def _reporte(self, **k):
        w = self.stdout.write
        ok = self.style.SUCCESS
        inf = self.style.HTTP_INFO
        warn = self.style.WARNING
        sep = "-" * 60

        total_espera = Reserva.objects.filter(estado=Reserva.Estado.EN_ESPERA).count()

        w(ok("\n" + "=" * 60))
        w(ok(" SEED PRE-DEMO LISTO - 7 Historias de Usuario"))
        w(ok("=" * 60))
        w(f"Contrasena de TODOS los usuarios: {self.password}")
        w(f"Hora de clases en vivo (HU2/HU3): {k['H']:02d}:00  (hoy {k['hoy']:%d/%m/%Y})")
        w(f"Fechas futuras usadas: f0={k['f0']:%d/%m/%Y}  f1={k['f1']:%d/%m/%Y}")
        if total_espera == TOTAL_ESPERA_OBJETIVO:
            w(ok(f"Total EN_ESPERA del sistema: {total_espera}  (OK: la anotacion de HU5 lo lleva a 10 -> dispara HU6)"))
        else:
            w(warn(f"Total EN_ESPERA del sistema: {total_espera}  (ATENCION: se esperaba {TOTAL_ESPERA_OBJETIVO}; "
                   f"hay reservas EN_ESPERA ajenas al seed. HU6 puede no dispararse al anotarse 1 cliente)."))

        w("\n" + ok("ORDEN SUGERIDO DE PRESENTACION: HU4 -> HU1 -> HU3 -> HU2 -> HU5 -> HU6 -> HU7"))

        w("\n" + sep)
        w(" HU4 - Generar QR por turno  (cliente)")
        w(sep)
        w("  Logueate como: ivannociti212+cliente@gmail.com")
        w("  Anda a Mis reservas -> reserva de Voley f0 17h -> 'Ver QR'.")
        w(inf(f"    URL directa: /asistencia/reserva/{k['reserva_qr'].pk}/qr/"))
        w("  Esc1: se genera y muestra el QR. Esc2: volve a entrar -> muestra el MISMO QR.")

        w("\n" + sep)
        w(" HU1 - Ver historial de asistencias  (cliente)")
        w(sep)
        w("  Mismo usuario (cliente). Mis reservas -> 'Ver historial de clases'.")
        w("  Veras 2 clases de ayer: una PRESENTE (Voley) y una AUSENTE (Futbol).")

        w("\n" + sep)
        w(" HU3 - Escanear QR  (empleado)")
        w(sep)
        w("  Cliente que muestra el QR: ivannociti212+escaneo@gmail.com")
        w("  Empleado que escanea:      ivannociti212+empleado@gmail.com")
        w("  Esc1 EXITOSO (en curso, sin marcar):")
        w(inf(f"    QR cliente: /asistencia/reserva/{k['a_e_ok'].reserva_id}/qr/   marcar: /asistencia/marcar/{k['a_e_ok'].codigo}/"))
        w("  Esc2 HORARIO INCORRECTO (clase ya vencida hoy):")
        w(inf(f"    marcar: /asistencia/marcar/{k['a_e_fv'].codigo}/   -> 'fuera de horario'"))
        w("  Esc3 YA UTILIZADO (asistencia ya registrada):")
        w(inf(f"    marcar: /asistencia/marcar/{k['a_e_ya'].codigo}/   -> 'ya registrada'"))

        w("\n" + sep)
        w(" HU2 - Registro manual por DNI  (empleado)")
        w(sep)
        w("  Logueate como empleado. Panel -> Marcar por DNI  (/asistencia/marcar-dni/)")
        w(f"  Esc1 EXITOSO        -> DNI {DNI_HU2_OK}  (clase en curso, pagada) -> Marcar presente.")
        w(f"  Esc2 SIN CLASE      -> DNI {DNI_HU2_SINCLASE}  (sin reservas) -> mensaje 'no tiene clase'.")
        w(f"  Esc3 CLASE VENCIDA  -> DNI {DNI_HU2_VENCIDA}  (clase ya finalizada hoy) -> mensaje 'no tiene clase'.")

        w("\n" + sep)
        w(" HU5 + HU6 - Unirse a lista de espera y Notificar admins")
        w(sep)
        w(f"  Estado inicial: {total_espera} clientes EN_ESPERA en el sistema.")
        w("  Logueate como cliente (ivannociti212+cliente@gmail.com).")
        w(f"  Reserva: Turno unico -> Futbol -> {k['f0']:%d/%m/%Y} -> 17hs (esta LLENO).")
        w("  -> 'Anotarme en lista de espera'. Con esto el total llega a 10:")
        w("     se dispara el mail a los admins (HU6). Revisa ivannociti212+admin@gmail.com.")
        w("  Esc2 (ya anotado): intenta de nuevo el mismo turno -> 'ya tenes otra reserva'.")

        w("\n" + sep)
        w(" HU7 - Ofrecer turno automaticamente  (sistema)")
        w(sep)
        w("  OFERTA DIRECTA al cancelar un titular:")
        w(f"    Esc1 (no abonado): logueate como {k['titular_1'].email} y CANCELA su")
        w(f"        reserva de Voley {k['f0']:%d/%m/%Y} 18hs -> se ofrece a ivannociti212+espera1@ (no abonado).")
        w(f"    Esc2 (abonado): logueate como {k['titular_2'].email} y CANCELA su")
        w(f"        reserva de Padel {k['f0']:%d/%m/%Y} 17hs -> se ofrece a ivannociti212+espera2@ (abonado, prioridad).")
        w("  OFERTA AL 2do tras VENCIMIENTO del 1ro (corre el command):")
        w(inf("        python manage.py procesar_invitaciones_vencidas"))
        w(f"    Esc3 (no abonados): Voley {k['f1']:%d/%m/%Y} 17hs -> vence espera3a -> se ofrece a espera3b.")
        w(f"    Esc4 (abonados):    Padel {k['f1']:%d/%m/%Y} 17hs -> vence espera4a -> se ofrece a espera4b.")
        w("  Todos los mails de invitacion llegan a ivannociti212+esperaN@gmail.com.")
        w(ok("\n" + "=" * 60 + "\n"))
