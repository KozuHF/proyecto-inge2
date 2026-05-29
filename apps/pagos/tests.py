from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.creditos.models import Credito
from apps.creditos.services import ContextoPagoCreditos
from apps.pagos.forms import TarjetaPagoForm
from apps.pagos.services import TIPO_TOTAL


class TarjetaPagoFormCreditosTestCase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="cred@test.com",
            nombre="Cred",
            apellido="Test",
            nro_documento="66666666",
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
        vence = timezone.now() + timedelta(days=30)
        Credito.objects.create(
            usuario=self.usuario,
            actividad=self.actividad,
            fecha_vencimiento=vence,
        )
        self.ctx = ContextoPagoCreditos(
            actividad=self.actividad,
            saldo=1,
            max_creditos=1,
            valor_credito=Decimal("5000.00"),
            regla_cobro=None,
        )

    def test_sin_cvv_si_creditos_cubren_total(self):
        opciones = [(TIPO_TOTAL, "Pago total", Decimal("5000.00"))]
        form = TarjetaPagoForm(
            {
                "tipo_pago": TIPO_TOTAL,
                "creditos_usados": "1",
                "modo_tarjeta": "guardada",
                "cvv": "",
            },
            opciones_pago=opciones,
            creditos_ctx=self.ctx,
            tarjeta_guardada=type("T", (), {"enmascarada": "**** 1971"})(),
            usuario=self.usuario,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.requiere_tarjeta)

    def test_creditos_cubren_abono_penalizado_segunda_quincena(self):
        """Mes penalizado: el valor del crédito debe ser precio completo, no el 20 % off."""
        from apps.turnos.abono_mensual import REGLA_SEGUNDA_QUINCENA
        from apps.turnos.models import CancelacionAbonoMensual

        for _ in range(3):
            CancelacionAbonoMensual.objects.create(
                usuario=self.usuario,
                anio_cancelacion=2026,
                mes_cancelacion=5,
            )
        vence = timezone.now() + timedelta(days=30)
        for _ in range(2):
            Credito.objects.create(
                usuario=self.usuario,
                actividad=self.actividad,
                fecha_vencimiento=vence,
            )
        ctx = ContextoPagoCreditos(
            actividad=self.actividad,
            saldo=2,
            max_creditos=2,
            valor_credito=Decimal("5000.00"),
            regla_cobro=REGLA_SEGUNDA_QUINCENA,
        )
        opciones = [("total", "Pago total", Decimal("10000.00"))]
        form = TarjetaPagoForm(
            {
                "tipo_pago": "total",
                "creditos_usados": "2",
                "modo_tarjeta": "guardada",
                "cvv": "",
            },
            opciones_pago=opciones,
            creditos_ctx=ctx,
            tarjeta_guardada=type("T", (), {"enmascarada": "**** 1971"})(),
            usuario=self.usuario,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.requiere_tarjeta)

    def test_cvv_obligatorio_si_queda_saldo_tarjeta(self):
        opciones = [(TIPO_TOTAL, "Pago total", Decimal("10000.00"))]
        form = TarjetaPagoForm(
            {
                "tipo_pago": TIPO_TOTAL,
                "creditos_usados": "1",
                "modo_tarjeta": "guardada",
                "cvv": "",
            },
            opciones_pago=opciones,
            creditos_ctx=self.ctx,
            tarjeta_guardada=type("T", (), {"enmascarada": "**** 1971"})(),
            usuario=self.usuario,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cvv", form.errors)


class CardValidationAndPaymentTestCase(TestCase):
    def test_any_16_digit_card_is_valid(self):
        from apps.pagos import tarjetas
        # A completely random 16 digit card should be valid
        numero_valido = "4556123456789012"
        self.assertEqual(tarjetas.validar_numero_tarjeta_campo(numero_valido), numero_valido)

    def test_invalid_length_card_is_rejected(self):
        from apps.pagos import tarjetas
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            tarjetas.validar_numero_tarjeta_campo("1234567890")

    def test_no_funds_card_still_has_no_funds(self):
        from apps.pagos import tarjetas
        self.assertFalse(tarjetas.pan_tiene_fondos("1509200001061970"))

    def test_other_cards_have_funds(self):
        from apps.pagos import tarjetas
        self.assertTrue(tarjetas.pan_tiene_fondos("4556123456789012"))
