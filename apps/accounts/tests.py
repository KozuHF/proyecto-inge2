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

        # Sin permiso: redirige al inicio (no 403)
        for url_name in ['panel_control', 'accounts:lista', 'accounts:crear_empleado', 'panel_turnos']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('home'))

    def test_employee_access(self):
        self.client.force_login(self.employee)

        # Panel general: permitido (200)
        response = self.client.get(reverse('panel_control'))
        self.assertEqual(response.status_code, 200)

        # Secciones solo de admin: redirige al inicio (no 403)
        for url_name in ['accounts:lista', 'accounts:crear_empleado', 'panel_turnos']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('home'))

    def test_admin_access(self):
        self.client.force_login(self.admin)

        # All access should be allowed (200)
        for url_name in ['panel_control', 'accounts:lista', 'accounts:crear_empleado', 'panel_turnos']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)


class AccesoCuentaAjenaTest(TestCase):
    """Un usuario no puede acceder a la cuenta de otro por URL."""

    def setUp(self):
        self.admin = Usuario.objects.create_user(
            email="admin2@test.com", nombre="Admin", apellido="Dos",
            nro_documento="91000001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.ADMIN, is_staff=True,
        )
        self.ana = Usuario.objects.create_user(
            email="ana@test.com", nombre="Ana", apellido="Uno",
            nro_documento="91000002", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.beto = Usuario.objects.create_user(
            email="beto@test.com", nombre="Beto", apellido="Dos",
            nro_documento="91000003", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )

    def test_detalle_cuenta_ajena_redirige(self):
        self.client.force_login(self.ana)
        resp = self.client.get(reverse("accounts:detalle", kwargs={"pk": self.beto.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("home"))

    def test_editar_cuenta_ajena_redirige(self):
        self.client.force_login(self.ana)
        resp = self.client.get(reverse("accounts:editar", kwargs={"pk": self.beto.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("home"))

    def test_propia_cuenta_accesible(self):
        self.client.force_login(self.ana)
        self.assertEqual(
            self.client.get(reverse("accounts:editar", kwargs={"pk": self.ana.pk})).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("accounts:detalle", kwargs={"pk": self.ana.pk})).status_code, 200
        )

    def test_admin_ve_cualquier_cuenta(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("accounts:detalle", kwargs={"pk": self.ana.pk})).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("accounts:editar", kwargs={"pk": self.ana.pk})).status_code, 200
        )

    def test_anonimo_va_a_login(self):
        resp = self.client.get(reverse("accounts:detalle", kwargs={"pk": self.ana.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

class EmployeeCreationFormTest(TestCase):
    def test_employee_creation_success_and_auto_generation(self):
        from apps.accounts.forms import EmpleadoCreacionForm
        from apps.accounts.models import Roles
        from datetime import date
        from django.utils import timezone

        form = EmpleadoCreacionForm(data={
            "nombre": "Pedro",
            "apellido": "Gómez",
            "email": "pedro@test.com",
            "password1": "Password123!",
            "password2": "Password123!"
        })

        self.assertTrue(form.is_valid(), form.errors)
        empleado = form.save()

        # Check generated DNI starts with 99 and has 8 digits
        self.assertEqual(len(empleado.nro_documento), 8)
        self.assertTrue(empleado.nro_documento.startswith("99"))
        self.assertTrue(empleado.nro_documento.isdigit())

        # Check birth date is approximately 20 years ago and valid
        hoy = timezone.now().date()
        edad = (
            hoy.year - empleado.fecha_nacimiento.year
            - ((hoy.month, hoy.day) < (empleado.fecha_nacimiento.month, empleado.fecha_nacimiento.day))
        )
        self.assertTrue(edad >= 18)

        # Check role and staff status
        self.assertEqual(empleado.rol, Roles.EMPLOYEE)
        self.assertTrue(empleado.is_staff)

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


class EmailNormalizacionTest(TestCase):
    """El email se estandariza en minúsculas y la unicidad es case-insensitive."""

    def _datos_registro(self, email):
        return {
            "nombre": "Ana",
            "apellido": "Lopez",
            "nro_documento": "50000001",
            "email": email,
            "fecha_nacimiento": "1990-01-01",
            "password1": "Password123!",
            "password2": "Password123!",
            "acepta_sin_impedimentos": True,
        }

    def test_create_user_normaliza_email(self):
        usuario = Usuario.objects.create_user(
            email="Mail@Mail.com",
            nombre="Ana",
            apellido="Lopez",
            nro_documento="50000010",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
        )
        self.assertEqual(usuario.email, "mail@mail.com")

    def test_save_normaliza_email(self):
        usuario = Usuario.objects.create_user(
            email="ana@test.com",
            nombre="Ana",
            apellido="Lopez",
            nro_documento="50000011",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
        )
        usuario.email = "ANA2@TEST.COM"
        usuario.save()
        usuario.refresh_from_db()
        self.assertEqual(usuario.email, "ana2@test.com")

    def test_registro_duplicado_case_insensitive(self):
        from apps.accounts.forms import UsuarioCreacionForm

        Usuario.objects.create_user(
            email="mail@mail.com",
            nombre="Ana",
            apellido="Lopez",
            nro_documento="50000020",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
        )
        form = UsuarioCreacionForm(data=self._datos_registro("MAIL@MAIL.COM"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registro_guarda_email_en_minusculas(self):
        from apps.accounts.forms import UsuarioCreacionForm

        form = UsuarioCreacionForm(data=self._datos_registro("Test@MAIL.com"))
        self.assertTrue(form.is_valid(), form.errors)
        usuario = form.save()
        self.assertEqual(usuario.email, "test@mail.com")

    def test_editar_propio_email_solo_cambia_case(self):
        from apps.accounts.forms import UsuarioPerfilForm

        usuario = Usuario.objects.create_user(
            email="cliente@test.com",
            nombre="Ana",
            apellido="Lopez",
            nro_documento="50000030",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
        )
        form = UsuarioPerfilForm(
            data={"nombre": "Ana", "apellido": "Lopez", "email": "CLIENTE@test.com"},
            instance=usuario,
        )
        self.assertTrue(form.is_valid(), form.errors)
        actualizado = form.save()
        self.assertEqual(actualizado.email, "cliente@test.com")


class MiCuentaNavbarVisibilidadTest(TestCase):
    """Los botones/datos exclusivos de clientes no se muestran a staff."""

    def setUp(self):
        self.cliente = Usuario.objects.create_user(
            email="cli@test.com", nombre="Cli", apellido="Ente",
            nro_documento="60000001", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.USER,
        )
        self.empleado = Usuario.objects.create_user(
            email="emp@test.com", nombre="Emp", apellido="Leado",
            nro_documento="60000002", fecha_nacimiento=date(1990, 1, 1),
            password="Password123!", rol=Roles.EMPLOYEE, is_staff=True,
        )

    def test_cliente_ve_botones_y_datos(self):
        # La página "Mi cuenta" incluye el navbar y no tiene CTAs de la home,
        # así que sirve para verificar navbar + datos en una sola request.
        self.client.force_login(self.cliente)
        cuenta = self.client.get(reverse("accounts:editar", kwargs={"pk": self.cliente.pk})).content.decode()
        self.assertIn("Reservar turno", cuenta)
        self.assertIn("Mis reservas", cuenta)
        self.assertIn("Número de documento", cuenta)
        self.assertIn("Tarjeta de crédito", cuenta)

    def test_staff_no_ve_botones_ni_datos(self):
        self.client.force_login(self.empleado)
        cuenta = self.client.get(reverse("accounts:editar", kwargs={"pk": self.empleado.pk})).content.decode()
        self.assertNotIn("Reservar turno", cuenta)
        self.assertNotIn("Mis reservas", cuenta)
        self.assertNotIn("Número de documento", cuenta)
        self.assertNotIn("Tarjeta de crédito", cuenta)
        self.assertNotIn("Mis créditos por deporte", cuenta)


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

