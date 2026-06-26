"""
Seed para la PRE-DEMO 2 (carpeta HUs_PreDemo2).

Prepara, de forma independiente por Historia de Usuario, el estado para mostrar:

  HU17 - Unirse a la lista de espera            (cliente)
  HU18 - Ofrecer turno automaticamente          (sistema)
  HU19 - Notificar a administradores            (sistema)
  HU29 - Generar QR por turno                   (cliente)
  HU30 - Escanear QR                            (empleado)
  HU33 - Registrar asistencia manual por DNI    (empleado)
  HU40 - Ver historial de asistencias           (cliente)

Cada HU usa usuarios y clases propios (no se pisan entre si). Las clases de
asistencia en vivo (HU29/HU30/HU33/HU40) usan hoy + hora actual para caer dentro
de la ventana de asistencia. Las de lista de espera (HU17/HU18/HU19) usan fechas
futuras habiles para que las invitaciones queden vigentes.

Notas (cambios respecto de los .txt):
- HU18: se saco el temporizador de 1 hora. La invitacion vence al inicio de la
  clase. Los escenarios 3 y 4 (el 2do recibe la invitacion) se muestran con el
  1ro RECHAZANDO la invitacion.
- HU19: el aviso a admins se dispara cuando el TOTAL global de EN_ESPERA llega a
  EXACTAMENTE 10. El seed deja el total en 9, asi la anotacion en vivo lo lleva a
  10. Recomendado: demostrar HU19 antes que HU17/HU18.

Uso:
    python manage.py seed_predemo2                 # hora actual
    python manage.py seed_predemo2 --hora 16       # fija la hora de las clases en vivo
    python manage.py seed_predemo2 --password X    # cambia la contrasena comun
"""
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.asistencia import services as asistencia_services
from apps.asistencia.models import Asistencia
from apps.turnos.models import (
    GrupoReservaMensual,
    HorarioDisponible,
    InvitacionCupo,
    Reserva,
    Turno,
    _validar_dia_habil,
)

PASSWORD_DEFECTO = "Prueba360!"
TOTAL_ESPERA_OBJETIVO = 9  # para que la anotacion en vivo de HU19 lleve a 10 (umbral)

# ── DNIs reservados para predemo2 (se borran y recrean) ───────────────────────
DNI_EMPLEADO = "90000201"
DNI_ADMIN    = "90000202"

# HU17
DNI_17_UNICO = "90000210"
DNI_17_ABONO = "90000211"
DNI_17_FILL1 = "90000212"
DNI_17_FILL2 = "90000213"

# HU18
DNI_18_TITA1 = "90000220"  # titular clase A1 (cancela)
DNI_18_FIRA1 = "90000221"  # 1ro EN_ESPERA no abonado (recibe al cancelar)
DNI_18_FIRA2 = "90000222"  # 1ro INVITADO no abonado (rechaza)
DNI_18_SECA2 = "90000223"  # 2do EN_ESPERA no abonado (recibe tras rechazo)
DNI_18_TITB1 = "90000224"  # titular clase B1 (cancela)
DNI_18_FIRB1 = "90000225"  # 1ro EN_ESPERA abonado (recibe al cancelar)
DNI_18_FIRB2 = "90000226"  # 1ro INVITADO abonado (rechaza)
DNI_18_SECB2 = "90000227"  # 2do EN_ESPERA abonado (recibe tras rechazo)

# HU19
DNI_19_TITULAR = "90000230"
DNI_19_RELLENO = [f"9000023{i}" for i in range(1, 9)]  # 90000231..90000238
DNI_19_DECIMO  = "90000239"  # se anota en vivo (10mo)

# HU29
DNI_29 = "90000240"

# HU30
DNI_30_OK     = "90000241"
DNI_30_HOR    = "90000242"
DNI_30_USADO  = "90000243"

# HU33 (DNIs del .txt, sin puntos)
DNI_33_OK       = "11222333"
DNI_33_SINCLASE = "11222334"
DNI_33_VENCIDA  = "22333444"
DNI_33_SENADO   = "22333445"

# HU40
DNI_40 = "90000250"

TODOS_LOS_DNI = [
    DNI_EMPLEADO, DNI_ADMIN,
    DNI_17_UNICO, DNI_17_ABONO, DNI_17_FILL1, DNI_17_FILL2,
    DNI_18_TITA1, DNI_18_FIRA1, DNI_18_FIRA2, DNI_18_SECA2,
    DNI_18_TITB1, DNI_18_FIRB1, DNI_18_FIRB2, DNI_18_SECB2,
    DNI_19_TITULAR, DNI_19_DECIMO,
    DNI_29, DNI_30_OK, DNI_30_HOR, DNI_30_USADO,
    DNI_33_OK, DNI_33_SINCLASE, DNI_33_VENCIDA, DNI_33_SENADO,
    DNI_40,
] + DNI_19_RELLENO


class Command(BaseCommand):
    help = "Prepara los datos para la Pre-Demo 2 (HUs 17, 18, 19, 29, 30, 33, 40)."

    def add_arguments(self, parser):
        parser.add_argument("--hora", type=int, default=None,
                            help="Hora (11-20) de las clases de asistencia en vivo. Default: hora actual.")
        parser.add_argument("--password", default=PASSWORD_DEFECTO)

    @transaction.atomic
    def handle(self, *args, **options):
        self.password = options["password"]

        ahora = timezone.localtime()
        H = options["hora"] if options["hora"] is not None else ahora.hour
        H = max(11, min(H, 20))          # garantiza H-3 >= 8 y H <= 20
        hv = H - 3                        # hora "ya vencida" hoy (ventana cerrada)

        hoy = timezone.localdate()
        f0, f1 = self._proximas_fechas_habiles(hoy, 2)

        self._reset()

        # Actividades (se crean si no existen).
        voley  = self._actividad(Actividad.Nombre.VOLEY, 8000)
        futbol = self._actividad(Actividad.Nombre.FUTBOL, 9000)
        basket = self._actividad(Actividad.Nombre.BASKET, 8500)
        paddle = self._actividad(Actividad.Nombre.PADDLE, 12000)

        # Usuarios comunes a la operacion (empleado escanea/marca; admin recibe avisos).
        empleado = self._usuario(DNI_EMPLEADO, "p2empleado", "Emi", "Empleado", Roles.EMPLOYEE, staff=True)
        self._usuario(DNI_ADMIN, "p2admin", "Ada", "Admin", Roles.ADMIN, staff=True)

        datos = {}
        self._hu29(voley, hoy, H, datos)
        self._hu30(paddle, hoy, H, hv, empleado, datos)
        self._hu33(basket, hoy, H, hv, datos)
        self._hu40(voley, paddle, hoy, hv, empleado, datos)
        self._hu17(futbol, voley, f0, datos)
        self._hu18(voley, paddle, f0, f1, datos)
        self._hu19(basket, f0, datos)   # ultimo: cuadra el total global a 9

        self._reporte(H=H, hv=hv, hoy=hoy, f0=f0, f1=f1, **datos)

    # ── Historias de Usuario ──────────────────────────────────────────────────

    def _hu29(self, voley, hoy, H, datos):
        """Generar QR: reserva paga sin Asistencia previa (el cliente la genera)."""
        u = self._usuario(DNI_29, "p2qr", "Quim", "VerQR", Roles.USER)
        r = self._reserva_paga(u, self._turno(voley, hoy, H, cupos=20))
        datos["hu29_reserva"] = r

    def _hu30(self, paddle, hoy, H, hv, empleado, datos):
        """Escanear QR: ok (en ventana), horario invalido (vencida), ya usado."""
        ok = self._usuario(DNI_30_OK, "p2scanok", "Sol", "ScanOk", Roles.USER)
        hor = self._usuario(DNI_30_HOR, "p2scanhor", "Hugo", "ScanHorario", Roles.USER)
        usado = self._usuario(DNI_30_USADO, "p2scanusado", "Uma", "ScanUsado", Roles.USER)

        t_now = self._turno(paddle, hoy, H, cupos=20)
        a_ok = self._asistencia(self._reserva_paga(ok, t_now), presente=False)
        a_usado = self._asistencia(self._reserva_paga(usado, t_now), presente=True, empleado=empleado)
        a_hor = self._asistencia(
            self._reserva_paga(hor, self._turno(paddle, hoy, hv, cupos=20)), presente=False
        )
        datos.update(hu30_ok=a_ok, hu30_hor=a_hor, hu30_usado=a_usado)

    def _hu33(self, basket, hoy, H, hv, datos):
        """Marcado por DNI: ok, sin clase, vencida, senado (badge pago pendiente)."""
        ok = self._usuario(DNI_33_OK, "p2dniok", "Dora", "DniOk", Roles.USER)
        self._usuario(DNI_33_SINCLASE, "p2dnisin", "Dan", "DniSinClase", Roles.USER)
        venc = self._usuario(DNI_33_VENCIDA, "p2dnivenc", "Dimas", "DniVencida", Roles.USER)
        sen = self._usuario(DNI_33_SENADO, "p2dnisen", "Delia", "DniSenado", Roles.USER)

        self._asistencia(self._reserva_paga(ok, self._turno(basket, hoy, H, cupos=20)), presente=False)
        self._asistencia(self._reserva_paga(venc, self._turno(basket, hoy, hv, cupos=20)), presente=False)
        self._reserva_senada(sen, self._turno(basket, hoy, H, cupos=20))
        # DNI_33_SINCLASE no tiene reservas.

    def _hu40(self, voley, paddle, hoy, hv, empleado, datos):
        """Historial: una clase pasada PRESENTE y otra AUSENTE (ventana cerrada)."""
        u = self._usuario(DNI_40, "p2hist", "Hilda", "Historial", Roles.USER)
        r_pres = self._reserva_paga(u, self._turno(voley, hoy, hv, cupos=20))
        self._asistencia(r_pres, presente=True, empleado=empleado)
        r_aus = self._reserva_paga(u, self._turno(paddle, hoy, hv, cupos=20))
        self._asistencia(r_aus, presente=False)

    def _hu17(self, futbol, voley, f0, datos):
        """Unirse a lista de espera: clase llena para turno unico y para abono."""
        # esc1 (no abonado, turno unico): Futbol f0 17h LLENO.
        self._horario(futbol, f0.weekday(), 17)
        fill1 = self._usuario(DNI_17_FILL1, "p2fill1", "Fede", "Relleno1", Roles.USER)
        self._reserva_paga(fill1, self._turno(futbol, f0, 17, cupos=1))
        self._usuario(DNI_17_UNICO, "p2lista17u", "Lara", "ListaUnico", Roles.USER)

        # esc2 (abonado mensual): Voley f0 18h LLENO (mismo dia de semana que f0).
        self._horario(voley, f0.weekday(), 18)
        fill2 = self._usuario(DNI_17_FILL2, "p2fill2", "Fabi", "Relleno2", Roles.USER)
        self._reserva_paga(fill2, self._turno(voley, f0, 18, cupos=1))
        self._usuario(DNI_17_ABONO, "p2lista17a", "Leo", "ListaAbono", Roles.USER)

    def _hu18(self, voley, paddle, f0, f1, datos):
        """Ofrecer turno: cancelar->1ro invitado; 1ro rechaza->2do invitado."""
        # A1: no abonado, oferta al cancelar el titular. Voley f0 19h.
        tit_a1 = self._usuario(DNI_18_TITA1, "p2tita1", "Tito", "TitularA1", Roles.USER)
        t_a1 = self._turno(voley, f0, 19, cupos=1)
        self._reserva_paga(tit_a1, t_a1)
        fir_a1 = self._usuario(DNI_18_FIRA1, "p2fira1", "Nora", "NoAbonadoA1", Roles.USER)
        self._reserva_espera(fir_a1, t_a1)

        # A2: no abonado, 1ro INVITADO (vigente) rechaza -> 2do EN_ESPERA. Voley f1 19h.
        fir_a2 = self._usuario(DNI_18_FIRA2, "p2fira2", "Pia", "NoAbonadoA2", Roles.USER)
        t_a2 = self._turno(voley, f1, 19, cupos=1)
        r_inv_a2 = self._reserva_invitado(fir_a2, t_a2)
        inv_a2 = self._invitacion_vigente(r_inv_a2, t_a2)
        sec_a2 = self._usuario(DNI_18_SECA2, "p2seca2", "Sol", "NoAbonadoA2b", Roles.USER)
        self._reserva_espera(sec_a2, t_a2)

        # B1: abonado, oferta al cancelar el titular. Padel f0 19h.
        tit_b1 = self._usuario(DNI_18_TITB1, "p2titb1", "Tina", "TitularB1", Roles.USER)
        t_b1 = self._turno(paddle, f0, 19, cupos=1)
        self._reserva_paga(tit_b1, t_b1)
        fir_b1 = self._usuario(DNI_18_FIRB1, "p2firb1", "Ari", "AbonadoB1", Roles.USER)
        r_esp_b1 = self._reserva_espera(fir_b1, t_b1, abono=True)
        self._grupo_abono(fir_b1, paddle, t_b1, r_esp_b1)

        # B2: abonado, 1ro INVITADO (vigente) rechaza -> 2do EN_ESPERA. Padel f1 19h.
        fir_b2 = self._usuario(DNI_18_FIRB2, "p2firb2", "Bea", "AbonadoB2", Roles.USER)
        t_b2 = self._turno(paddle, f1, 19, cupos=1)
        r_inv_b2 = self._reserva_invitado(fir_b2, t_b2, abono=True)
        self._grupo_abono(fir_b2, paddle, t_b2, r_inv_b2)
        inv_b2 = self._invitacion_vigente(r_inv_b2, t_b2)
        sec_b2 = self._usuario(DNI_18_SECB2, "p2secb2", "Bruno", "AbonadoB2b", Roles.USER)
        r_esp_b2 = self._reserva_espera(sec_b2, t_b2, abono=True)
        self._grupo_abono(sec_b2, paddle, t_b2, r_esp_b2)

        datos.update(
            hu18_tit_a1=tit_a1, hu18_t_a1=t_a1,
            hu18_tit_b1=tit_b1, hu18_t_b1=t_b1,
            hu18_inv_a2=inv_a2, hu18_inv_b2=inv_b2,
        )

    def _hu19(self, basket, f0, datos):
        """Notificar admin: deja el total global de EN_ESPERA en 9."""
        self._horario(basket, f0.weekday(), 16)
        titular = self._usuario(DNI_19_TITULAR, "p2tit19", "Tomas", "Titular19", Roles.USER)
        turno = self._turno(basket, f0, 16, cupos=1)
        self._reserva_paga(titular, turno)  # llena el turno

        actuales = Reserva.objects.filter(estado=Reserva.Estado.EN_ESPERA).count()
        faltan = TOTAL_ESPERA_OBJETIVO - actuales
        for i in range(max(0, faltan)):
            u = self._usuario(DNI_19_RELLENO[i], f"p2esp19_{i}", f"Esp{i}", "Espera19", Roles.USER)
            self._reserva_espera(u, turno)

        # Cliente que se anota en vivo (el 10mo). No queda en espera todavia.
        self._usuario(DNI_19_DECIMO, "p2decimo19", "Deca", "Decimo19", Roles.USER)
        datos["hu19_turno"] = turno

    # ── Helpers de creacion ────────────────────────────────────────────────────

    def _proximas_fechas_habiles(self, desde: date, n: int) -> list:
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

    def _horario(self, actividad, dia_semana, hora):
        HorarioDisponible.objects.update_or_create(
            actividad=actividad, dia_semana=dia_semana, hora=hora,
            defaults={"activo": True, "cupos": 1, "precio": actividad.precio_turno},
        )

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
            referencia_pago="SEED-PREDEMO2",
        )

    def _reserva_senada(self, usuario, turno) -> Reserva:
        return Reserva.objects.create(
            usuario=usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
            precio_abonado=turno.precio_efectivo,
            referencia_pago="SEED-PREDEMO2-SENA",
        )

    def _reserva_espera(self, usuario, turno, *, abono=False) -> Reserva:
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

    def _invitacion_vigente(self, reserva, turno) -> InvitacionCupo:
        """Invitacion PENDIENTE que vence al inicio de la clase (futura => vigente)."""
        inicio = timezone.make_aware(
            datetime(turno.fecha.year, turno.fecha.month, turno.fecha.day, turno.hora, 0)
        )
        return InvitacionCupo.objects.create(
            reserva=reserva,
            estado=InvitacionCupo.Estado.PENDIENTE,
            fecha_vencimiento=inicio,
        )

    def _grupo_abono(self, usuario, actividad, turno, reserva) -> GrupoReservaMensual:
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

    # ── Idempotencia ───────────────────────────────────────────────────────────

    def _reset(self):
        Usuario.objects.filter(nro_documento__in=TODOS_LOS_DNI).delete()
        # HU19 depende del contador GLOBAL de lista de espera. Para que sea
        # determinista, limpiamos las reservas EN_ESPERA de prueba que hayan
        # quedado de otros seeds/pruebas (en esta base de demo es todo descartable).
        self._espera_limpiadas = Reserva.objects.filter(
            estado=Reserva.Estado.EN_ESPERA
        ).delete()[0]

    # ── Reporte / roadmap ───────────────────────────────────────────────────────

    def _reporte(self, **k):
        w = self.stdout.write
        ok = self.style.SUCCESS
        inf = self.style.HTTP_INFO
        warn = self.style.WARNING
        sep = "-" * 64

        total_espera = Reserva.objects.filter(estado=Reserva.Estado.EN_ESPERA).count()

        w(ok("\n" + "=" * 64))
        w(ok(" SEED PRE-DEMO 2 LISTO"))
        w(ok("=" * 64))
        w(f"Contrasena de TODOS los usuarios: {self.password}")
        w(f"Clases en vivo (HU29/HU30/HU33/HU40): hoy {k['hoy']:%d/%m/%Y} a las {k['H']:02d}:00")
        w(f"  (hora ya vencida hoy para 'fuera de ventana': {k['hv']:02d}:00)")
        w(f"Fechas futuras (HU17/HU18/HU19): f0={k['f0']:%d/%m/%Y}  f1={k['f1']:%d/%m/%Y}")
        limpiadas = getattr(self, "_espera_limpiadas", 0)
        if limpiadas:
            w(f"Limpieza: se eliminaron {limpiadas} reservas EN_ESPERA de prueba previas.")
        if total_espera == TOTAL_ESPERA_OBJETIVO:
            w(ok(f"Total EN_ESPERA del sistema: {total_espera}  (OK: el 10mo en vivo dispara HU19)"))
        else:
            w(warn(f"Total EN_ESPERA del sistema: {total_espera}  (se esperaba {TOTAL_ESPERA_OBJETIVO}; "
                   "hay EN_ESPERA ajenas al seed: HU19 puede no dispararse con 1 anotacion)"))

        w("\n" + ok("ORDEN SUGERIDO: HU29 -> HU40 -> HU30 -> HU33 -> HU19 -> HU17 -> HU18"))
        w(warn("  (HU19 ANTES de HU17/HU18: el contador de lista de espera es global)"))

        # HU29
        w("\n" + sep)
        w(" HU29 - Generar QR por turno  (cliente)")
        w(sep)
        w("  Login: ivannociti212+p2qr@gmail.com")
        w("  Mis reservas -> reserva de Voley de hoy -> 'Ver QR'.")
        w(inf(f"    URL directa: /asistencia/reserva/{k['hu29_reserva'].pk}/qr/"))
        w("  Esc1: se genera el QR. Esc2: volve a entrar -> muestra el MISMO QR.")

        # HU40
        w("\n" + sep)
        w(" HU40 - Ver historial de asistencias  (cliente)")
        w(sep)
        w("  Login: ivannociti212+p2hist@gmail.com")
        w("  Mis reservas -> 'Ver historial de clases'.")
        w("  Veras 2 clases de hoy ya vencidas: una PRESENTE (Voley) y una AUSENTE (Padel).")

        # HU30
        w("\n" + sep)
        w(" HU30 - Escanear QR  (empleado)")
        w(sep)
        w("  Empleado que escanea: ivannociti212+p2empleado@gmail.com  (panel -> Escanear)")
        w("  Esc1 EXITOSO (en ventana, sin marcar):")
        w(inf(f"    QR cliente p2scanok -> /asistencia/reserva/{k['hu30_ok'].reserva_id}/qr/"))
        w(inf(f"    marcar: /asistencia/marcar/{k['hu30_ok'].codigo}/"))
        w("  Esc2 HORARIO INVALIDO (clase ya vencida hoy):")
        w(inf(f"    marcar: /asistencia/marcar/{k['hu30_hor'].codigo}/"))
        w("  Esc3 YA REGISTRADA:")
        w(inf(f"    marcar: /asistencia/marcar/{k['hu30_usado'].codigo}/"))

        # HU33
        w("\n" + sep)
        w(" HU33 - Registro manual por DNI  (empleado)")
        w(sep)
        w("  Login empleado. Panel -> Marcar por DNI  (/asistencia/marcar-dni/)")
        w(f"  Esc1 EXITOSO       -> DNI {DNI_33_OK}  (clase en curso, pagada) -> Marcar presente.")
        w(f"  Esc2 SIN CLASE     -> DNI {DNI_33_SINCLASE}  (sin reservas) -> 'no tiene clase en el horario actual'.")
        w(f"  Esc3 CLASE VENCIDA -> DNI {DNI_33_VENCIDA}  (clase ya finalizada hoy) -> mismo mensaje.")
        w(f"  Esc4 SENADA        -> DNI {DNI_33_SENADO}  (Basket, senada) -> badge 'Pago pendiente' (sin boton).")

        # HU19
        w("\n" + sep)
        w(" HU19 - Notificar a administradores  (sistema)")
        w(sep)
        w(f"  Estado inicial: {total_espera} clientes EN_ESPERA en el sistema.")
        w("  Login: ivannociti212+p2decimo19@gmail.com")
        w(f"  Reserva: Turno unico -> Basket -> {k['f0']:%d/%m/%Y} -> 16hs (esta LLENO).")
        w("  -> 'Anotarme en lista de espera'. El total llega a 10 -> mail a admins.")
        w("  Revisa la casilla ivannociti212+p2admin@gmail.com (HU19).")

        # HU17
        w("\n" + sep)
        w(" HU17 - Unirse a la lista de espera  (cliente)")
        w(sep)
        w("  Esc1 (no abonado, turno unico): login ivannociti212+p2lista17u@gmail.com")
        w(f"    Reservar -> Turno unico -> Futbol -> {k['f0']:%d/%m/%Y} -> 17hs (LLENO) -> 'Anotarme en lista de espera'.")
        w("  Esc2 (abonado mensual): login ivannociti212+p2lista17a@gmail.com")
        w(f"    Reservar -> Abonado mensual -> Voley -> dia {k['f0']:%A} -> 18hs -> en el listado, la clase")
        w(f"    del {k['f0']:%d/%m/%Y} aparece LLENA -> 'Anotarse en lista de espera'.")

        # HU18
        w("\n" + sep)
        w(" HU18 - Ofrecer turno automaticamente  (sistema)")
        w(sep)
        w("  OFERTA DIRECTA al cancelar un titular:")
        w(f"    Esc1 (no abonado): login {k['hu18_tit_a1'].email}")
        w(f"        CANCELA su reserva de Voley {k['f0']:%d/%m/%Y} 19hs -> se ofrece a p2fira1 (no abonado).")
        w(f"    Esc2 (abonado): login {k['hu18_tit_b1'].email}")
        w(f"        CANCELA su reserva de Padel {k['f0']:%d/%m/%Y} 19hs -> se ofrece a p2firb1 (abonado, prioridad).")
        w("  OFERTA AL 2do cuando el 1ro RECHAZA:")
        w(f"    Esc3 (no abonados): login ivannociti212+p2fira2@gmail.com -> abrir invitacion -> Rechazar")
        w(inf(f"        /turnos/invitacion/{k['hu18_inv_a2'].token}/  -> se ofrece a p2seca2."))
        w(f"    Esc4 (abonados): login ivannociti212+p2firb2@gmail.com -> abrir invitacion -> Rechazar")
        w(inf(f"        /turnos/invitacion/{k['hu18_inv_b2'].token}/  -> se ofrece a p2secb2."))
        w("  Los mails de invitacion llegan a ivannociti212+...@gmail.com.")
        w(ok("\n" + "=" * 64 + "\n"))
