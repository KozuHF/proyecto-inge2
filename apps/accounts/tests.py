from datetime import date
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import Usuario, Roles

class PanelPermissionsTest(TestCase):
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

    def test_anonymous_redirects(self):
        # Anonymous should be redirected to login
        for url_name in ['panel_control', 'accounts:lista', 'accounts:crear_empleado', 'panel_turnos']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    def test_client_user_access(self):
        self.client.force_login(self.client_user)
        
        # Access to panel_control should be forbidden (403)
        response = self.client.get(reverse('panel_control'))
        self.assertEqual(response.status_code, 403)

        # Access to list and create employee should be forbidden (403)
        for url_name in ['accounts:lista', 'accounts:crear_empleado']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403)

        # Access to panel_turnos should be forbidden (403)
        response = self.client.get(reverse('panel_turnos'))
        self.assertEqual(response.status_code, 403)

    def test_employee_access(self):
        self.client.force_login(self.employee)

        # Access to panel_control should be allowed (200)
        response = self.client.get(reverse('panel_control'))
        self.assertEqual(response.status_code, 200)

        # Access to list and create employee should be forbidden (403)
        for url_name in ['accounts:lista', 'accounts:crear_empleado']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 403)

        # Access to panel_turnos should be forbidden (403)
        response = self.client.get(reverse('panel_turnos'))
        self.assertEqual(response.status_code, 403)

    def test_admin_access(self):
        self.client.force_login(self.admin)

        # All access should be allowed (200)
        for url_name in ['panel_control', 'accounts:lista', 'accounts:crear_empleado', 'panel_turnos']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)

class EmployeeCreationFormTest(TestCase):
    def test_employee_minor_validation_message(self):
        from apps.accounts.forms import EmpleadoCreacionForm
        from datetime import date
        from django.utils import timezone

        # Create data with an under 18 date of birth
        hoy = timezone.now().date()
        minor_dob = date(hoy.year - 17, hoy.month, hoy.day)

        form = EmpleadoCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "44444444",
            "email": "pedro@test.com",
            "fecha_nacimiento": minor_dob.strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!"
        })

        self.assertFalse(form.is_valid())
        self.assertIn("fecha_nacimiento", form.errors)
        self.assertEqual(
            form.errors["fecha_nacimiento"][0],
            "No se pueden registrar empleados menores de edad en el sistema."
        )

    def test_customer_minor_validation_message(self):
        from apps.accounts.forms import UsuarioCreacionForm
        from datetime import date
        from django.utils import timezone

        hoy = timezone.now().date()
        minor_dob = date(hoy.year - 17, hoy.month, hoy.day)

        form = UsuarioCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "44444444",
            "email": "pedro@test.com",
            "fecha_nacimiento": minor_dob.strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True
        })

        self.assertFalse(form.is_valid())
        self.assertIn("fecha_nacimiento", form.errors)
        self.assertEqual(
            form.errors["fecha_nacimiento"][0],
            "El usuario debe tener al menos 18 años para registrarse. Acercarse a la sede con un adulto responsable para el registro."
        )


class DNIValidationTest(TestCase):
    def test_dni_exactly_8_digits_valid(self):
        from apps.accounts.forms import UsuarioCreacionForm
        from datetime import date
        form = UsuarioCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "12345678", # 8 digits - Valid
            "email": "pedro@test.com",
            "fecha_nacimiento": date(1990, 1, 1).strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True
        })
        self.assertTrue(form.is_valid())

    def test_dni_less_than_8_digits_invalid(self):
        from apps.accounts.forms import UsuarioCreacionForm
        from datetime import date
        form = UsuarioCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "1234567", # 7 digits - Invalid
            "email": "pedro@test.com",
            "fecha_nacimiento": date(1990, 1, 1).strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nro_documento", form.errors)
        self.assertEqual(
            form.errors["nro_documento"][0],
            "El número de documento (DNI) debe contener exactamente 8 números."
        )

    def test_dni_more_than_8_digits_invalid(self):
        from apps.accounts.forms import UsuarioCreacionForm
        from datetime import date
        form = UsuarioCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "123456789", # 9 digits - Invalid
            "email": "pedro@test.com",
            "fecha_nacimiento": date(1990, 1, 1).strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nro_documento", form.errors)

    def test_dni_non_numeric_invalid(self):
        from apps.accounts.forms import UsuarioCreacionForm
        from datetime import date
        form = UsuarioCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "nro_documento": "1234567A", # Non-numeric - Invalid
            "email": "pedro@test.com",
            "fecha_nacimiento": date(1990, 1, 1).strftime("%Y-%m-%d"),
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True
        })
        self.assertFalse(form.is_valid())
        self.assertIn("nro_documento", form.errors)

