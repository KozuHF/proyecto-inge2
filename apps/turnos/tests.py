from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.turnos.models import Turno, Reserva


class TurnosPanelTestCase(TestCase):
    def setUp(self):
        # Create users
        self.admin = Usuario.objects.create_user(
            email="admin@test.com",
            nombre="Admin",
            apellido="Test",
            nro_documento="11111111",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.ADMIN,
            is_staff=True
        )
        self.employee = Usuario.objects.create_user(
            email="employee@test.com",
            nombre="Employee",
            apellido="Test",
            nro_documento="22222222",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.EMPLOYEE,
            is_staff=True
        )
        self.client_user = Usuario.objects.create_user(
            email="user@test.com",
            nombre="Client",
            apellido="Test",
            nro_documento="33333333",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.USER,
            is_staff=False
        )
        self.other_user = Usuario.objects.create_user(
            email="other@test.com",
            nombre="Other",
            apellido="Test",
            nro_documento="44444444",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.USER,
            is_staff=False
        )

        # Get or create activity and shift
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000}
        )
        # Note: 2026-05-18 is a Monday (días hábiles is 0 to 5)
        self.turno = Turno.objects.create(
            actividad=self.actividad,
            fecha=date(2026, 5, 18),
            hora=10,
            cupos=1
        )

    def test_cupos_reduction_invalid(self):
        """Cannot reduce slots below the number of currently confirmed reservations."""
        # Create a confirmed reservation
        Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )
        # Verify reducing cupos to 0 (which is less than 1 confirmed reservation) raises ValidationError
        self.turno.cupos = 0
        with self.assertRaises(ValidationError) as ctx:
            self.turno.full_clean()
        self.assertIn("No podés reducir los cupos", str(ctx.exception))

    def test_waitlist_invitation_on_cupo_increase(self):
        """Al aumentar cupos, el de la lista de espera recibe una invitación (queda INVITADO)."""
        r1 = Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )
        # 2da reserva en lista de espera
        r2 = Reserva.objects.create(
            usuario=self.other_user,
            turno=self.turno,
            estado=Reserva.Estado.EN_ESPERA
        )

        self.assertEqual(r1.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(r2.estado, Reserva.Estado.EN_ESPERA)

        # Aumentar cupos a 2 y guardar el turno → se ofrece el cupo, no se promueve directo
        self.turno.cupos = 2
        self.turno.save()

        r2.refresh_from_db()
        self.assertEqual(r2.estado, Reserva.Estado.INVITADO)
        self.assertTrue(hasattr(r2, "invitacion"))
        self.assertEqual(r2.invitacion.estado, r2.invitacion.Estado.PENDIENTE)

    def test_panel_views_access_permissions(self):
        """Only administrators can access panel_turnos, editar_turno, and eliminar_turno."""
        # Test anonymous redirection
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

        # Cliente sin permiso: redirige al inicio (no 403)
        self.client.force_login(self.client_user)
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('home'))

        # Empleado sin permiso (es solo de admin): redirige al inicio
        self.client.force_login(self.employee)
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('home'))

        # Test admin allowed (200)
        self.client.force_login(self.admin)
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

    def test_editar_turno_view_post(self):
        """Admin can modify a turn via the edit view, validating the form fields."""
        self.client.force_login(self.admin)
        url = reverse('editar_turno', kwargs={'pk': self.turno.pk})

        post_data = {
            'actividad': self.actividad.pk,
            'fecha': '2026-05-26',  # Attempts to change, but is disabled
            'hora': 12,  # valid
            'cupos': 5  # valid
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('panel_turnos'))

        self.turno.refresh_from_db()
        # Fecha and Actividad should remain unchanged because they are disabled fields in the form
        self.assertEqual(self.turno.fecha, date(2026, 5, 18))
        self.assertEqual(self.turno.actividad, self.actividad)
        self.assertEqual(self.turno.hora, 12)
        self.assertEqual(self.turno.cupos, 5)

    def test_editar_turno_hora_choices(self):
        """TurnoForm dynamically filters out hours that are already occupied by other turnos on that date/activity."""
        # Create another Turno for the same activity and date but different hour (e.g., 15)
        turno_conflicto = Turno.objects.create(
            actividad=self.actividad,
            fecha=self.turno.fecha,
            hora=15,
            cupos=3
        )
        self.client.force_login(self.admin)
        
        # Load the edit page for self.turno
        url = reverse('editar_turno', kwargs={'pk': self.turno.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        form = response.context['form']
        choices = [c[0] for c in form.fields['hora'].choices]
        
        # 15 should be excluded because it's occupied by turno_conflicto
        self.assertNotIn(15, choices)
        # self.turno's own hour (which is self.turno.hora, e.g. 10) should be in choices to allow keeping it
        self.assertIn(self.turno.hora, choices)

    def test_eliminar_turno_view_post(self):
        """Admin can delete a turn via the delete view, deleting associated reservations."""
        # Create a reservation
        reserva = Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )

        self.client.force_login(self.admin)

        # Verify the GET request warns about 1 reservation
        url = reverse('eliminar_turno', kwargs={'pk': self.turno.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response,
                            "La eliminación de turnos puede cancelar de forma permanente las reservas asociadas a los mismos.")

        # Perform the POST request to delete the shift
        response = self.client.post(url)
        self.assertRedirects(response, reverse('panel_turnos'))

        # Verify both Turno and Reserva are deleted
        self.assertFalse(Turno.objects.filter(pk=self.turno.pk).exists())
        self.assertFalse(Reserva.objects.filter(pk=reserva.pk).exists())

    def test_crear_horario_disponible_view_get(self):
        """Verify that the schedule creation view loads successfully on GET."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse('turnos:crear_horario_disponible'))
        self.assertEqual(response.status_code, 200)

    def test_panel_turnos_sunday(self):
        """Sunday should return es_dia_invalido=True, empty turnos list, and closed alert notice."""
        self.client.force_login(self.admin)
        url = reverse('panel_turnos')
        # 2026-05-24 is Sunday
        response = self.client.get(url, {'fecha': '2026-05-24'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['es_dia_invalido'])
        self.assertEqual(len(response.context['turnos']), 0)
        self.assertContains(response, "Establecimiento Cerrado")

    def test_panel_turnos_vacios_filter(self):
        """Filtering by 'vacios' should exclude shifts with confirmed reservations."""
        # Create a confirmed reservation on the shift
        Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )
        self.client.force_login(self.admin)
        url = reverse('panel_turnos')
        # 2026-05-18 is a Monday (has our shift and virtual slots)

        # When filtering by 'todos'
        response_all = self.client.get(url, {'fecha': '2026-05-18', 'estado_ocupacion': 'todos'})
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(len(response_all.context['turnos']), 1)
        self.assertIn(self.turno, response_all.context['turnos'])

        # When filtering by 'vacios'
        response_vacios = self.client.get(url, {'fecha': '2026-05-18', 'estado_ocupacion': 'vacios'})
        self.assertEqual(response_vacios.status_code, 200)
        self.assertEqual(len(response_vacios.context['turnos']), 0)
        self.assertNotIn(self.turno, response_vacios.context['turnos'])

    def test_panel_turnos_holiday(self):
        """Holiday should return es_dia_invalido=True, es_feriado=True, empty turnos, and closed alert notice."""
        self.client.force_login(self.admin)
        url = reverse('panel_turnos')
        # 2026-05-25 is May 25 (Revolución de Mayo - holiday)
        response = self.client.get(url, {'fecha': '2026-05-25'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['es_dia_invalido'])
        self.assertTrue(response.context['es_feriado'])
        self.assertEqual(len(response.context['turnos']), 0)
        self.assertContains(response, "Establecimiento Cerrado")
        self.assertContains(response, "cerrado por feriado nacional")

    def test_crear_turno_on_holiday_invalid(self):
        """Attempting to create a Turno on a holiday raises a ValidationError."""
        turno_holiday = Turno(
            actividad=self.actividad,
            fecha=date(2026, 5, 25),  # Holiday
            hora=12,
            cupos=5
        )
        with self.assertRaises(ValidationError) as ctx:
            turno_holiday.full_clean()
        self.assertIn("cerrado por feriado nacional", str(ctx.exception))

    def test_propagate_modifications_to_future(self):
        """Admin can modify a turn and propagate changes (cupos, pricing) to future occurrences."""
        self.client.force_login(self.admin)
        url = reverse('editar_turno', kwargs={'pk': self.turno.pk})

        # Modify cupos to 3, precio_override to 6500, and tick modifying future occurrences
        post_data = {
            'actividad': self.actividad.pk,
            'fecha': '2026-05-18',  # Monday
            'hora': 10,
            'cupos': 3,
            'precio_override': Decimal("6500.00"),
            'modificar_futuros': True
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('panel_turnos'))

        self.turno.refresh_from_db()
        self.assertEqual(self.turno.cupos, 3)
        self.assertEqual(self.turno.precio_override, Decimal("6500.00"))

        # Check that weekly future turnos (on Mondays at 10:00) have been created/updated
        # Next Monday is 2026-05-25 (holiday, closed, so skipped)
        # Next-next Monday is 2026-06-01
        future_date = date(2026, 6, 1)
        future_turno = Turno.objects.filter(
            actividad=self.actividad,
            fecha=future_date,
            hora=10
        ).first()
        self.assertIsNotNone(future_turno)
        self.assertEqual(future_turno.cupos, 3)
        self.assertEqual(future_turno.precio_override, Decimal("6500.00"))

    def test_precio_override_calculations(self):
        """Verify that precio_override is respected for reservations and abono calculations."""
        # Ensure activity price is exactly 5000
        self.actividad.precio_turno = Decimal("5000.00")
        self.actividad.save()

        # Create a shift with override price
        override_turno = Turno.objects.create(
            actividad=self.actividad,
            fecha=date(2026, 5, 19),  # Tuesday
            hora=10,
            cupos=5,
            precio_override=Decimal("7500.00")
        )

        # Create a single reservation for this shift
        reserva = Reserva.objects.create(
            usuario=self.client_user,
            turno=override_turno,
            estado=Reserva.Estado.CONFIRMADA,
            tipo_reserva=Reserva.TipoReserva.INDIVIDUAL
        )
        self.assertEqual(reserva.monto_total, Decimal("7500.00"))
        self.assertEqual(reserva.monto_sena, Decimal("3750.00"))  # 50%

        # Calculate abono amount containing this shift
        from apps.turnos.abono_mensual import monto_total_desde_fechas
        total, regla, desc = monto_total_desde_fechas(
            self.actividad,
            [date(2026, 5, 12), date(2026, 5, 19)]
        )
        # 2026-05-19 has override (7500), 2026-05-12 doesn't exist in DB so defaults to activity price (5000)
        # Total should be 7500 + 5000 = 12500
        self.assertEqual(total, Decimal("12500.00"))

    def test_bulk_future_deletion_cancels_reservations(self):
        """Admin can delete a shift and all future weekly occurrences, canceling/deleting future reservations."""
        # Create a future Monday shift
        future_date = date(2026, 6, 1)
        future_turno = Turno.objects.create(
            actividad=self.actividad,
            fecha=future_date,
            hora=10,
            cupos=5
        )
        # Create reservations
        r1 = Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )
        r2 = Reserva.objects.create(
            usuario=self.client_user,
            turno=future_turno,
            estado=Reserva.Estado.CONFIRMADA
        )

        self.client.force_login(self.admin)

        # Perform POST to delete this and all future weekly occurrences
        url = reverse('eliminar_turno', kwargs={'pk': self.turno.pk})
        post_data = {
            'tipo_eliminacion': 'todos_futuros'
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('panel_turnos'))

        # Verify both current and future turnos are deleted, and their reservations are gone
        self.assertFalse(Turno.objects.filter(pk=self.turno.pk).exists())
        self.assertFalse(Turno.objects.filter(pk=future_turno.pk).exists())
        self.assertFalse(Reserva.objects.filter(pk=r1.pk).exists())
        self.assertFalse(Reserva.objects.filter(pk=r2.pk).exists())

    def test_paso_fecha_form_holiday(self):
        """PasoFechaForm should be invalid on a holiday."""
        from apps.turnos.forms import PasoFechaForm
        from unittest.mock import patch
        from django.utils import timezone
        from datetime import datetime

        # Mock timezone.now() to return May 1, 2026 so that May 25 is in the future
        with patch('apps.turnos.forms.timezone.now') as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2026, 5, 1))
            form = PasoFechaForm(data={'fecha': '2026-05-25'})  # Monday May 25 is holiday (Revolución de Mayo)
            self.assertFalse(form.is_valid())
            self.assertIn('fecha', form.errors)
            self.assertIn('feriado nacional', form.errors['fecha'][0])

    def test_obtener_fechas_candidatas_varios_excludes_holidays(self):
        """obtener_fechas_candidatas_varios should exclude Mondays that are holidays (e.g. May 25, 2026)."""
        from django.utils import timezone
        from unittest.mock import patch
        from datetime import datetime
        from apps.turnos.models import HorarioDisponible

        # Crear un HorarioDisponible para lunes (weekday=0) a las 10 hs
        HorarioDisponible.objects.get_or_create(
            actividad=self.actividad,
            dia_semana=0,  # lunes
            hora=10,
            defaults={"activo": True, "cupos": 5, "precio": 8500},
        )

        # Mock timezone.now() to return May 1, 2026 so that May 25 is in the future
        with patch('apps.turnos.forms.timezone.now') as mock_now:
            mock_now.return_value = timezone.make_aware(datetime(2026, 5, 1, 10, 0, 0))

            from apps.turnos.services import obtener_fechas_candidatas_varios
            # Reference date: Monday May 18, 2026
            ref_date = date(2026, 5, 18)
            # Call service to get candidate dates for May 2026
            candidatas = obtener_fechas_candidatas_varios(ref_date, 10, actividad=self.actividad)

            # May 2026 has Mondays on 4, 11, 18, 25.
            # Since May 25 is a holiday, it must be excluded.
            self.assertIn(date(2026, 5, 4), candidatas)
            self.assertIn(date(2026, 5, 11), candidatas)
            self.assertIn(date(2026, 5, 18), candidatas)
            self.assertNotIn(date(2026, 5, 25), candidatas)

    def test_contacto_view(self):
        """Verify contact page loading and email addresses display."""
        url = reverse('contacto')

        # Test GET request
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ponte en contacto")
        self.assertContains(response, "contacto@club360.com")
        self.assertContains(response, "sugerencias@club360.com")
        self.assertContains(response, "reclamos@club360.com")


class HistorialClasesTestCase(TestCase):
    """Sin clases históricas, entrar al historial redirige a Mis reservas."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="hist@test.com", nombre="His", apellido="Torial",
            nro_documento="66800001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL, defaults={"cupos": 5, "precio_turno": 5000}
        )

    def test_sin_historial_redirige_a_mis_reservas(self):
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("turnos:historial_clases"))
        self.assertRedirects(resp, reverse("turnos:mis_reservas"))

    def test_con_historial_muestra_la_pagina(self):
        turno = Turno.objects.create(
            actividad=self.actividad, fecha=date(2020, 1, 2), hora=10, cupos=5
        )
        Reserva.objects.create(
            usuario=self.usuario, turno=turno,
            estado=Reserva.Estado.CONFIRMADA, estado_pago=Reserva.EstadoPago.PAGADO,
            precio_abonado=5000,
        )
        self.client.force_login(self.usuario)
        resp = self.client.get(reverse("turnos:historial_clases"))
        self.assertEqual(resp.status_code, 200)


class PuedePagarListaEsperaTestCase(TestCase):
    """El botón Pagar no debe aparecer para una reserva en lista de espera."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="pp@test.com", nombre="Pe", apellido="Pe",
            nro_documento="66700001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL, defaults={"cupos": 5, "precio_turno": 5000}
        )

    def _reserva(self, estado, *, hora):
        turno = Turno.objects.create(
            actividad=self.actividad, fecha=date(2035, 1, 2), hora=hora, cupos=5
        )
        return Reserva.objects.create(
            usuario=self.usuario, turno=turno, estado=estado,
            estado_pago=Reserva.EstadoPago.PENDIENTE, tipo_reserva=Reserva.TipoReserva.INDIVIDUAL,
        )

    def test_en_espera_no_puede_pagar(self):
        reserva = self._reserva(Reserva.Estado.EN_ESPERA, hora=10)
        self.assertFalse(reserva.puede_pagar)

    def test_confirmada_pendiente_puede_pagar(self):
        reserva = self._reserva(Reserva.Estado.CONFIRMADA, hora=11)
        self.assertTrue(reserva.puede_pagar)

    def test_invitado_puede_pagar(self):
        reserva = self._reserva(Reserva.Estado.INVITADO, hora=12)
        self.assertTrue(reserva.puede_pagar)


class PenalidadCancelacionesTestCase(TestCase):
    """Penalización: 3+ cancelaciones de abono mensual en un mes → sin 20 % el mes siguiente."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="penal@test.com",
            nombre="Penal",
            apellido="Test",
            nro_documento="55555555",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.USER,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": Decimal("5000.00")},
        )
        self.actividad.precio_turno = Decimal("5000.00")
        self.actividad.save()

    def _registrar_cancelaciones(self, cantidad: int, anio: int, mes: int):
        from apps.turnos.models import CancelacionAbonoMensual

        for _ in range(cantidad):
            CancelacionAbonoMensual.objects.create(
                usuario=self.usuario,
                anio_cancelacion=anio,
                mes_cancelacion=mes,
            )

    def test_tres_cancelaciones_quitan_descuento_mes_siguiente(self):
        from apps.turnos.abono_mensual import REGLA_SEGUNDA_QUINCENA, monto_total_desde_fechas
        from apps.turnos.penalidad_cancelaciones import usuario_penalizado_descuento_segunda_quincena

        self._registrar_cancelaciones(3, 2026, 5)
        self.assertTrue(
            usuario_penalizado_descuento_segunda_quincena(self.usuario, 2026, 6)
        )
        fechas = [date(2026, 6, 16), date(2026, 6, 23)]
        total, regla, descuento = monto_total_desde_fechas(
            self.actividad, fechas, usuario=self.usuario, anio=2026, mes=6
        )
        self.assertEqual(regla, REGLA_SEGUNDA_QUINCENA)
        self.assertEqual(descuento, Decimal("0"))
        self.assertEqual(total, Decimal("10000.00"))

    def test_menos_de_tres_cancelaciones_mantiene_descuento(self):
        from apps.turnos.abono_mensual import monto_total_desde_fechas

        self._registrar_cancelaciones(2, 2026, 5)
        fechas = [date(2026, 6, 16), date(2026, 6, 23)]
        total, _, descuento = monto_total_desde_fechas(
            self.actividad, fechas, usuario=self.usuario, anio=2026, mes=6
        )
        self.assertEqual(descuento, Decimal("0.20"))
        self.assertEqual(total, Decimal("8000.00"))

    def test_beneficio_se_restaura_al_tercer_mes(self):
        from apps.turnos.penalidad_cancelaciones import usuario_penalizado_descuento_segunda_quincena

        self._registrar_cancelaciones(3, 2026, 5)
        self.assertFalse(
            usuario_penalizado_descuento_segunda_quincena(self.usuario, 2026, 7)
        )

    def test_mensaje_reserva_sin_beneficio(self):
        from apps.turnos.penalidad_cancelaciones import mensaje_sin_beneficio_segunda_quincena

        self._registrar_cancelaciones(3, 2026, 5)
        msg = mensaje_sin_beneficio_segunda_quincena(self.usuario, 2026, 6)
        self.assertIsNotNone(msg)
        self.assertIn("junio", msg.lower())
        self.assertIn("2026", msg)
        self.assertIn("no puede acceder", msg.lower())


class HorarioDisponibleValidationTestCase(TestCase):
    def setUp(self):
        from apps.actividades.models import Actividad
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000}
        )

    def test_clean_validation_without_future_turnos(self):
        """
        If a schedule exists but there are no future turnos in the database,
        creating another schedule in the same slot should pass validation.
        """
        from apps.turnos.models import HorarioDisponible
        from apps.turnos.forms import HorarioDisponibleForm

        # Create initial schedule
        h1 = HorarioDisponible.objects.create(
            actividad=self.actividad,
            dia_semana=1,  # Tuesday
            hora=10,
            cupos=5,
            precio=6000,
            activo=True
        )

        # There are no Turnos in the database at all.
        # Try to validate a form for a new schedule in the same slot
        form = HorarioDisponibleForm(data={
            "actividad": self.actividad.pk,
            "dia_semana": 1,
            "hora": 10,
            "cupos": 5,
            "precio": 6500,
            "activo": True
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_clean_validation_with_future_turnos(self):
        """
        If a schedule exists and there are future turnos in the DB,
        validation should fail for a new schedule.
        """
        from apps.turnos.models import HorarioDisponible, Turno
        from apps.turnos.forms import HorarioDisponibleForm
        from datetime import date

        # Create schedule
        h1 = HorarioDisponible.objects.create(
            actividad=self.actividad,
            dia_semana=1,  # Tuesday
            hora=10,
            cupos=5,
            precio=6000,
            activo=True
        )

        # Create a future Turno on Tuesday (e.g. June 2, 2026 is a Tuesday)
        Turno.objects.create(
            actividad=self.actividad,
            fecha=date(2026, 6, 2),
            hora=10,
            cupos=5
        )

        # Form validation should fail now
        form = HorarioDisponibleForm(data={
            "actividad": self.actividad.pk,
            "dia_semana": 1,
            "hora": 10,
            "cupos": 5,
            "precio": 6500,
            "activo": True
        })
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        self.assertIn("Ya existe un horario activo y con turnos futuros", form.errors["__all__"][0])


class ComprobanteReservaMailTestCase(TestCase):
    """Comprobante por mail al registrar un turno."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="cliente@test.com",
            nombre="Juan",
            apellido="Perez",
            nro_documento="55555555",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.USER,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )
        # 2026-06-01 es lunes
        self.turno = Turno.objects.create(
            actividad=self.actividad, fecha=date(2026, 6, 1), hora=18, cupos=5
        )

    def _reserva(self, *, estado_pago=Reserva.EstadoPago.PENDIENTE, abonado=None, turno=None):
        return Reserva.objects.create(
            usuario=self.usuario,
            turno=turno or self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=estado_pago,
            precio_abonado=abonado,
        )

    def _html(self, msg):
        """Devuelve el cuerpo HTML de la alternativa del mail."""
        return msg.alternatives[0][0]

    def test_comprobante_turno_unico_pagado(self):
        from django.core import mail
        from apps.turnos.notificaciones import enviar_comprobante_reserva

        reserva = self._reserva(estado_pago=Reserva.EstadoPago.PAGADO, abonado=Decimal("5000.00"))
        enviado = enviar_comprobante_reserva(
            self.usuario, reserva, referencia="PG-ABC123", tipo_pago="total"
        )

        self.assertTrue(enviado)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["cliente@test.com"])
        self.assertEqual(msg.subject, "Comprobante de pago - Club360")
        # Tiene alternativa HTML
        self.assertTrue(msg.alternatives)
        self.assertEqual(msg.alternatives[0][1], "text/html")
        html = self._html(msg)
        self.assertIn("Comprobante de pago", html)
        self.assertIn("Pagado", html)
        self.assertIn("PG-ABC123", html)
        self.assertIn("18:00", html)

    def test_comprobante_senado_muestra_saldo(self):
        from django.core import mail
        from apps.turnos.notificaciones import enviar_comprobante_reserva

        # Seña 50% de 5000 = 2500, saldo 2500
        reserva = self._reserva(estado_pago=Reserva.EstadoPago.SENADO, abonado=Decimal("2500.00"))
        enviado = enviar_comprobante_reserva(
            self.usuario, reserva, referencia="PG-SENA1", tipo_pago="sena"
        )

        self.assertTrue(enviado)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Comprobante de seña - Club360")
        html = self._html(msg)
        self.assertIn("Comprobante de seña", html)
        self.assertIn("Señado", html)
        self.assertIn("Saldo pendiente", html)
        self.assertIn("2500", html)  # saldo
        self.assertIn("Saldo pend.", msg.body)  # versión texto

    def test_comprobante_abono_un_solo_mail(self):
        from django.core import mail
        from apps.turnos.notificaciones import enviar_comprobante_reserva

        turno2 = Turno.objects.create(
            actividad=self.actividad, fecha=date(2026, 6, 8), hora=18, cupos=5
        )
        r1 = self._reserva(estado_pago=Reserva.EstadoPago.PAGADO, abonado=Decimal("4500.00"))
        r2 = self._reserva(estado_pago=Reserva.EstadoPago.PAGADO, abonado=Decimal("4500.00"), turno=turno2)

        enviado = enviar_comprobante_reserva(
            self.usuario, [r1, r2], referencia="PG-XYZ", tipo_pago="total"
        )

        self.assertTrue(enviado)
        self.assertEqual(len(mail.outbox), 1)  # un solo mail por registración
        self.assertIn("Abono mensual", self._html(mail.outbox[0]))

    def test_comprobante_pendiente_sin_pago(self):
        from django.core import mail
        from apps.turnos.notificaciones import enviar_comprobante_reserva

        reserva = self._reserva(estado_pago=Reserva.EstadoPago.PENDIENTE, abonado=None)
        enviar_comprobante_reserva(self.usuario, reserva)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Comprobante de reserva - Club360")
        self.assertIn("Pago pendiente", self._html(msg))
        self.assertIn("Pago pendiente", msg.body)

    def test_sin_email_no_envia(self):
        from django.core import mail
        from apps.turnos.notificaciones import enviar_comprobante_reserva

        self.usuario.email = ""
        reserva = self._reserva(estado_pago=Reserva.EstadoPago.PAGADO, abonado=Decimal("5000.00"))
        enviado = enviar_comprobante_reserva(self.usuario, reserva)

        self.assertFalse(enviado)
        self.assertEqual(len(mail.outbox), 0)


class ListaEsperaInvitacionTestCase(TestCase):
    """Lista de espera con invitación por rol, cobro al aceptar y aviso al admin."""

    def setUp(self):
        self.admin = Usuario.objects.create_user(
            email="admin-le@test.com", nombre="Admin", apellido="LE",
            nro_documento="10000001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.ADMIN, is_staff=True,
        )
        self.titular = Usuario.objects.create_user(
            email="titular@test.com", nombre="Titu", apellido="Lar",
            nro_documento="10000002", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.no_abonado = Usuario.objects.create_user(
            email="noab@test.com", nombre="No", apellido="Abonado",
            nro_documento="10000003", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.abonado = Usuario.objects.create_user(
            email="ab@test.com", nombre="Si", apellido="Abonado",
            nro_documento="10000004", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.actividad, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )
        # 2026-06-01 es lunes
        self.turno = Turno.objects.create(
            actividad=self.actividad, fecha=date(2026, 6, 1), hora=10, cupos=1
        )

    def _hacer_abonado(self, usuario, actividad):
        """Crea un abono mensual activo del usuario en la actividad."""
        from apps.turnos.models import GrupoReservaMensual
        otro_turno = Turno.objects.create(
            actividad=actividad, fecha=date(2026, 6, 8), hora=10, cupos=5
        )
        grupo = GrupoReservaMensual.objects.create(
            usuario=usuario, actividad=actividad, dia_semana=0, hora=10,
            anio=2026, mes=6,
        )
        Reserva.objects.create(
            usuario=usuario, turno=otro_turno, estado=Reserva.Estado.CONFIRMADA,
            tipo_reserva=Reserva.TipoReserva.VARIOS, grupo_mensual=grupo,
        )
        return grupo

    def test_prioridad_abonado_sobre_no_abonado(self):
        from apps.turnos.models import InvitacionCupo

        confirmada = Reserva.objects.create(
            usuario=self.titular, turno=self.turno, estado=Reserva.Estado.CONFIRMADA
        )
        # El no abonado entra ANTES a la lista de espera
        r_no_ab = Reserva.objects.create(
            usuario=self.no_abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        # El abonado entra después, pero tiene prioridad por ser abonado de la actividad
        self._hacer_abonado(self.abonado, self.actividad)
        r_ab = Reserva.objects.create(
            usuario=self.abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )

        confirmada.cancelar()

        r_ab.refresh_from_db()
        r_no_ab.refresh_from_db()
        self.assertEqual(r_ab.estado, Reserva.Estado.INVITADO)
        self.assertEqual(r_no_ab.estado, Reserva.Estado.EN_ESPERA)
        self.assertTrue(
            InvitacionCupo.objects.filter(reserva=r_ab, estado=InvitacionCupo.Estado.PENDIENTE).exists()
        )

    def test_confirmar_por_pago(self):
        from apps.turnos import lista_espera
        from apps.turnos.models import InvitacionCupo

        confirmada = Reserva.objects.create(
            usuario=self.titular, turno=self.turno, estado=Reserva.Estado.CONFIRMADA
        )
        invitado = Reserva.objects.create(
            usuario=self.no_abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        confirmada.cancelar()
        invitado.refresh_from_db()
        self.assertEqual(invitado.estado, Reserva.Estado.INVITADO)

        lista_espera.confirmar_por_pago(invitado)

        invitado.refresh_from_db()
        self.assertEqual(invitado.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(invitado.invitacion.estado, InvitacionCupo.Estado.ACEPTADA)

    def test_rechazar_ofrece_al_siguiente(self):
        from apps.turnos import lista_espera

        confirmada = Reserva.objects.create(
            usuario=self.titular, turno=self.turno, estado=Reserva.Estado.CONFIRMADA
        )
        r1 = Reserva.objects.create(
            usuario=self.no_abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        r2 = Reserva.objects.create(
            usuario=self.abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        confirmada.cancelar()
        r1.refresh_from_db()
        self.assertEqual(r1.estado, Reserva.Estado.INVITADO)

        lista_espera.rechazar(r1.invitacion)

        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.estado, Reserva.Estado.CANCELADA)
        self.assertEqual(r2.estado, Reserva.Estado.INVITADO)

    def test_expiracion_ofrece_al_siguiente(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.turnos import lista_espera
        from apps.turnos.models import InvitacionCupo

        confirmada = Reserva.objects.create(
            usuario=self.titular, turno=self.turno, estado=Reserva.Estado.CONFIRMADA
        )
        r1 = Reserva.objects.create(
            usuario=self.no_abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        r2 = Reserva.objects.create(
            usuario=self.abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        confirmada.cancelar()
        r1.refresh_from_db()
        inv = r1.invitacion
        # Forzar el vencimiento al pasado
        inv.fecha_vencimiento = timezone.now() - timedelta(minutes=1)
        inv.save(update_fields=["fecha_vencimiento"])

        n = lista_espera.expirar_invitaciones_vencidas()

        self.assertEqual(n, 1)
        inv.refresh_from_db()
        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(inv.estado, InvitacionCupo.Estado.VENCIDA)
        self.assertEqual(r1.estado, Reserva.Estado.CANCELADA)
        self.assertEqual(r2.estado, Reserva.Estado.INVITADO)

    def test_aviso_admin_al_llegar_al_umbral(self):
        from django.core import mail
        from django.test import override_settings
        from apps.turnos import lista_espera

        with override_settings(UMBRAL_AVISO_LISTA_ESPERA=3):
            # 2 en espera: todavía no avisa
            for i in range(2):
                t = Turno.objects.create(
                    actividad=self.actividad, fecha=date(2026, 6, 1), hora=11 + i, cupos=1
                )
                Reserva.objects.create(
                    usuario=self.titular, turno=t, estado=Reserva.Estado.EN_ESPERA
                )
            lista_espera.chequear_umbral_admin()
            self.assertEqual(len(mail.outbox), 0)

            # La 3ra cruza el umbral: avisa una vez
            t = Turno.objects.create(
                actividad=self.actividad, fecha=date(2026, 6, 1), hora=20, cupos=1
            )
            Reserva.objects.create(
                usuario=self.titular, turno=t, estado=Reserva.Estado.EN_ESPERA
            )
            lista_espera.chequear_umbral_admin()
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("lista de espera", mail.outbox[0].subject.lower())
            self.assertIn(self.admin.email, mail.outbox[0].to)

    def test_invitacion_dispara_mail(self):
        from django.core import mail

        confirmada = Reserva.objects.create(
            usuario=self.titular, turno=self.turno, estado=Reserva.Estado.CONFIRMADA
        )
        Reserva.objects.create(
            usuario=self.no_abonado, turno=self.turno, estado=Reserva.Estado.EN_ESPERA
        )
        confirmada.cancelar()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.no_abonado.email])
        self.assertIn("cupo", mail.outbox[0].subject.lower())


class UserReservationConflictTestCase(TestCase):
    def setUp(self):
        from apps.actividades.models import Actividad
        from apps.accounts.models import Usuario, Roles
        self.usuario = Usuario.objects.create_user(
            email="conflicto@test.com",
            nombre="Pedro",
            apellido="Conflicto",
            nro_documento="77778888",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.USER,
        )
        self.actividad_futbol, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.FUTBOL,
            defaults={"cupos": 5, "precio_turno": 5000},
        )
        self.actividad_basquet, _ = Actividad.objects.get_or_create(
            nombre=Actividad.Nombre.BASKET,
            defaults={"cupos": 5, "precio_turno": 5000},
        )
        # Create a turno for Futbol on 2026-06-01 (Monday) at 10:00
        self.turno_futbol = Turno.objects.create(
            actividad=self.actividad_futbol,
            fecha=date(2026, 6, 1),
            hora=10,
            cupos=5
        )
        # Create a booking/reserva for this user on that turno
        Reserva.objects.create(
            usuario=self.usuario,
            turno=self.turno_futbol,
            estado=Reserva.Estado.CONFIRMADA
        )

    def test_paso_hora_validation_fails_if_already_reserved(self):
        from apps.turnos.forms import PasoHoraForm
        # The user already has a reservation on 2026-06-01 at 10:00 (in Fútbol)
        # Trying to select 10:00 on the same date (even for Basquet) should fail validation.
        horas_info = [{"hora": 10, "libres": 5, "lleno": False, "en_espera": 0}]
        form = PasoHoraForm(
            data={"hora": 10},
            horas_info=horas_info,
            usuario=self.usuario,
            fecha=date(2026, 6, 1)
        )
        self.assertFalse(form.is_valid())
        self.assertIn("hora", form.errors)
        self.assertEqual(
            form.errors["hora"][0],
            "No podés seleccionar un horario en el que ya tenés otra reserva."
        )

    def test_paso_seleccion_fechas_validation_fails_if_already_reserved(self):
        from apps.turnos.forms import PasoSeleccionFechasForm
        # Trying to select 2026-06-01 in a series at 10:00 should fail validation
        fechas_candidatas = [date(2026, 6, 1), date(2026, 6, 8)]
        form = PasoSeleccionFechasForm(
            data={"fechas": ["2026-06-01", "2026-06-08"]},
            fechas_candidatas=fechas_candidatas,
            usuario=self.usuario,
            hora=10
        )
        self.assertFalse(form.is_valid())
        self.assertIn("fechas", form.errors)
        self.assertEqual(
            form.errors["fechas"][0],
            "No podés seleccionar un día en el que ya tenés otra reserva a la misma hora."
        )
