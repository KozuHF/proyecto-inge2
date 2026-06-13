from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.turnos.models import Turno, Reserva
from apps.asistencia import services
from apps.asistencia.models import Asistencia


class AsistenciaBaseTestCase(TestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user(
            email="cli@test.com", nombre="Cli", apellido="Ente",
            nro_documento="70000001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.otro = Usuario.objects.create_user(
            email="otro@test.com", nombre="Otro", apellido="User",
            nro_documento="70000002", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.empleado = Usuario.objects.create_user(
            email="emp@test.com", nombre="Emp", apellido="Leado",
            nro_documento="70000003", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.EMPLOYEE, is_staff=True,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL, defaults={"cupos": 5, "precio_turno": 5000}
        )

    def _reserva(self, *, fecha, usuario=None, estado=Reserva.Estado.CONFIRMADA,
                 estado_pago=Reserva.EstadoPago.PAGADO, hora=10):
        turno = Turno.objects.create(actividad=self.actividad, fecha=fecha, hora=hora, cupos=5)
        return Reserva.objects.create(
            usuario=usuario or self.cliente, turno=turno,
            estado=estado, estado_pago=estado_pago, precio_abonado=5000,
        )

    def _reserva_en_ventana(self, **kw):
        """Reserva de hoy a la hora actual: 'ahora' cae dentro de la ventana."""
        hora = timezone.localtime().hour
        return self._reserva(fecha=timezone.localdate(), hora=hora, **kw)

    def _reserva_abono(self, *, fecha, hora=10, estado_pago=Reserva.EstadoPago.PENDIENTE):
        """Reserva de abono mensual (grupo del mes de `fecha`) con su pago."""
        from apps.turnos.models import GrupoReservaMensual

        turno = Turno.objects.create(actividad=self.actividad, fecha=fecha, hora=hora, cupos=5)
        grupo = GrupoReservaMensual.objects.create(
            usuario=self.cliente, actividad=self.actividad,
            dia_semana=fecha.weekday(), hora=hora,
            anio=fecha.year, mes=fecha.month,
            regla_cobro="primera_quincena",
        )
        return Reserva.objects.create(
            usuario=self.cliente, turno=turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=estado_pago,
            tipo_reserva=Reserva.TipoReserva.VARIOS,
            grupo_mensual=grupo,
        )

    def _reserva_abono_en_ventana(self, **kw):
        hora = timezone.localtime().hour
        return self._reserva_abono(fecha=timezone.localdate(), hora=hora, **kw)


class ServiciosAsistenciaTest(AsistenciaBaseTestCase):
    def test_crea_asistencia_solo_para_pagada_confirmada(self):
        reserva = self._reserva(fecha=date(2026, 6, 1))
        a1 = services.obtener_o_crear_asistencia(reserva)
        a2 = services.obtener_o_crear_asistencia(reserva)
        self.assertEqual(a1.pk, a2.pk)  # idempotente
        self.assertEqual(Asistencia.objects.count(), 1)

    def test_rechaza_no_pagada(self):
        reserva = self._reserva(fecha=date(2026, 6, 1), estado_pago=Reserva.EstadoPago.PENDIENTE)
        with self.assertRaises(ValidationError):
            services.obtener_o_crear_asistencia(reserva)

    def test_marcar_exito_dentro_de_ventana(self):
        reserva = self._reserva_en_ventana()
        asistencia = services.obtener_o_crear_asistencia(reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertTrue(res.exito)
        self.assertEqual(res.estado, "registrada")
        asistencia.refresh_from_db()
        self.assertTrue(asistencia.presente)
        self.assertEqual(asistencia.registrado_por, self.empleado)
        self.assertIsNotNone(asistencia.fecha_registro)

    def test_marcar_rechaza_clase_futura(self):
        reserva = self._reserva(fecha=date(2035, 1, 2))  # mucho antes de la ventana
        asistencia = services.obtener_o_crear_asistencia(reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertFalse(res.exito)
        self.assertEqual(res.estado, "fuera_de_ventana")
        asistencia.refresh_from_db()
        self.assertFalse(asistencia.presente)

    def test_marcar_rechaza_clase_pasada(self):
        reserva = self._reserva(fecha=date(2020, 1, 2))  # ya finalizó la ventana
        asistencia = services.obtener_o_crear_asistencia(reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertFalse(res.exito)
        self.assertEqual(res.estado, "fuera_de_ventana")

    def test_marcar_idempotente(self):
        reserva = self._reserva_en_ventana()
        asistencia = services.obtener_o_crear_asistencia(reserva)
        services.marcar_asistencia(asistencia.codigo, self.empleado)
        res2 = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertTrue(res2.exito)
        self.assertEqual(res2.estado, "ya_registrada")

    def test_qr_disponible_segun_ventana(self):
        futura = self._reserva(fecha=date(2035, 1, 2), hora=10)
        pasada = self._reserva(fecha=date(2020, 1, 2), hora=11)
        no_pagada = self._reserva(fecha=date(2035, 1, 2), hora=12, estado_pago=Reserva.EstadoPago.PENDIENTE)
        self.assertTrue(services.qr_disponible(futura))    # clase futura: se muestra
        self.assertFalse(services.qr_disponible(pasada))   # ya terminó: no se muestra
        self.assertFalse(services.qr_disponible(no_pagada))  # no pagada: no se muestra

    def test_abonado_pendiente_tiene_qr_y_puede_marcar(self):
        """El abonado tiene QR desde la reserva, aunque el abono esté impago."""
        reserva = self._reserva_abono_en_ventana()
        self.assertTrue(services.qr_disponible(reserva))
        asistencia = services.obtener_o_crear_asistencia(reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertTrue(res.exito)
        self.assertEqual(res.estado, "registrada")

    def test_abonado_pagado_funciona_igual(self):
        reserva = self._reserva_abono_en_ventana(estado_pago=Reserva.EstadoPago.PAGADO)
        self.assertTrue(services.qr_disponible(reserva))
        asistencia = services.obtener_o_crear_asistencia(reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertTrue(res.exito)

    def test_abonado_plazo_vencido_bloquea_qr_y_marcado(self):
        """Abono impago con plazo vencido (pasó el día 10 de su mes): sin QR ni marcado."""
        # Turno el 5 del mes (día 1-10) de un mes pasado → plazo vencido seguro.
        reserva = self._reserva_abono(fecha=date(2020, 3, 5))
        self.assertFalse(services.qr_disponible(reserva))
        with self.assertRaises(ValidationError):
            services.obtener_o_crear_asistencia(reserva)
        # Si la asistencia ya existía de antes, el marcado también se rechaza.
        asistencia = Asistencia.objects.create(reserva=reserva)
        res = services.marcar_asistencia(asistencia.codigo, self.empleado)
        self.assertFalse(res.exito)
        self.assertEqual(res.estado, "no_elegible")
        self.assertIn("abono", res.mensaje.lower())

    def test_individual_senado_sigue_sin_qr(self):
        """Regresión: el turno individual señado (50%) no tiene QR."""
        reserva = self._reserva(fecha=date(2035, 1, 2), estado_pago=Reserva.EstadoPago.SENADO)
        self.assertFalse(services.qr_disponible(reserva))
        with self.assertRaises(ValidationError):
            services.obtener_o_crear_asistencia(reserva)

    def test_marcar_codigo_inexistente(self):
        import uuid
        res = services.marcar_asistencia(uuid.uuid4(), self.empleado)
        self.assertFalse(res.exito)
        self.assertEqual(res.estado, "no_elegible")


class VistasAsistenciaTest(AsistenciaBaseTestCase):
    def test_qr_reserva_dueño(self):
        reserva = self._reserva(fecha=date(2035, 1, 2))  # clase futura: ventana abierta
        self.client.force_login(self.cliente)
        resp = self.client.get(reverse("asistencia:qr_reserva", kwargs={"pk": reserva.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<svg", resp.content)  # QR renderizado

    def test_qr_no_disponible_si_ventana_cerrada(self):
        reserva = self._reserva(fecha=date(2020, 1, 2))  # clase pasada: ventana cerrada
        self.client.force_login(self.cliente)
        resp = self.client.get(reverse("asistencia:qr_reserva", kwargs={"pk": reserva.pk}))
        self.assertEqual(resp.status_code, 410)
        self.assertContains(resp, "QR no disponible", status_code=410)
        self.assertNotContains(resp, "Mostrale este código al empleado", status_code=410)

    def test_qr_reserva_ajena_404(self):
        reserva = self._reserva(fecha=date(2035, 1, 2))
        self.client.force_login(self.otro)
        resp = self.client.get(reverse("asistencia:qr_reserva", kwargs={"pk": reserva.pk}))
        self.assertEqual(resp.status_code, 404)

    def test_marcar_cliente_prohibido(self):
        reserva = self._reserva(fecha=timezone.localdate())
        asistencia = services.obtener_o_crear_asistencia(reserva)
        self.client.force_login(self.cliente)
        resp = self.client.get(reverse("asistencia:marcar", kwargs={"codigo": asistencia.codigo}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("home"))

    def test_marcar_empleado_get_y_post(self):
        reserva = self._reserva_en_ventana()
        asistencia = services.obtener_o_crear_asistencia(reserva)
        self.client.force_login(self.empleado)
        url = reverse("asistencia:marcar", kwargs={"codigo": asistencia.codigo})
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        asistencia.refresh_from_db()
        self.assertTrue(asistencia.presente)

    def test_marcar_get_muestra_pago_pendiente_de_abono(self):
        reserva = self._reserva_abono_en_ventana()
        asistencia = services.obtener_o_crear_asistencia(reserva)
        self.client.force_login(self.empleado)
        resp = self.client.get(reverse("asistencia:marcar", kwargs={"codigo": asistencia.codigo}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pago pendiente (abono)")

    def test_escanear_empleado_ok_cliente_prohibido(self):
        url = reverse("asistencia:escanear")
        self.client.force_login(self.empleado)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.cliente)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("home"))
