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

    def test_waitlist_promotion_on_cupo_increase(self):
        """Waitlisted reservations are automatically promoted to CONFIRMADA when cupos are increased."""
        # Create 1st reservation (confirmed since cupos=1)
        r1 = Reserva.objects.create(
            usuario=self.client_user,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA
        )
        # Create 2nd reservation (waitlisted)
        r2 = Reserva.objects.create(
            usuario=self.other_user,
            turno=self.turno,
            estado=Reserva.Estado.EN_ESPERA
        )

        self.assertEqual(r1.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(r2.estado, Reserva.Estado.EN_ESPERA)

        # Increase cupos to 2 and save the shift
        self.turno.cupos = 2
        self.turno.save()

        # Refresh r2 from database
        r2.refresh_from_db()
        self.assertEqual(r2.estado, Reserva.Estado.CONFIRMADA)

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

        # Test client user forbidden (403)
        self.client.force_login(self.client_user)
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

        # Test employee forbidden (403)
        self.client.force_login(self.employee)
        for url_name, kwargs in [
            ('panel_turnos', None),
            ('editar_turno', {'pk': self.turno.pk}),
            ('eliminar_turno', {'pk': self.turno.pk})
        ]:
            url = reverse(url_name, kwargs=kwargs)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

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

        num_actividades = Actividad.objects.count()
        total_slots = num_actividades * 14

        # When filtering by 'todos'
        response_all = self.client.get(url, {'fecha': '2026-05-18', 'estado_ocupacion': 'todos'})
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(len(response_all.context['turnos']), total_slots)

        # When filtering by 'vacios'
        response_vacios = self.client.get(url, {'fecha': '2026-05-18', 'estado_ocupacion': 'vacios'})
        self.assertEqual(response_vacios.status_code, 200)
        self.assertEqual(len(response_vacios.context['turnos']), total_slots - 1)
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
            defaults={"activo": True},
        )

        # Mock timezone.now() to return May 1, 2026
        with patch('django.utils.timezone.now') as mock_now:
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