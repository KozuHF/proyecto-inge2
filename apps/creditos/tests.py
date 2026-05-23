from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Roles, Usuario
from apps.actividades.models import Actividad
from apps.turnos.abono_mensual import REGLA_SEGUNDA_QUINCENA

from .models import Credito
from .services import validar_creditos_pago, valor_credito_por_turno


class ValidarCreditosPenalidadTestCase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            email="credpen@test.com",
            nombre="Pen",
            apellido="Test",
            nro_documento="77777777",
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
        for _ in range(2):
            Credito.objects.create(
                usuario=self.usuario,
                actividad=self.actividad,
                fecha_vencimiento=vence,
            )

    def test_valor_credito_penalizado_sin_descuento(self):
        from apps.turnos.models import CancelacionAbonoMensual

        for _ in range(3):
            CancelacionAbonoMensual.objects.create(
                usuario=self.usuario,
                anio_cancelacion=2026,
                mes_cancelacion=5,
            )
        valor = valor_credito_por_turno(
            self.actividad,
            REGLA_SEGUNDA_QUINCENA,
            self.usuario,
            2026,
            6,
        )
        self.assertEqual(valor, Decimal("5000.00"))

    def test_dos_creditos_cubren_abono_penalizado_con_valor_contexto(self):
        valor_ctx = Decimal("5000.00")
        monto_tarjeta, descuento, usados = validar_creditos_pago(
            self.usuario,
            self.actividad,
            2,
            2,
            Decimal("10000.00"),
            REGLA_SEGUNDA_QUINCENA,
            valor_credito=valor_ctx,
        )
        self.assertEqual(usados, 2)
        self.assertEqual(descuento, Decimal("10000.00"))
        self.assertEqual(monto_tarjeta, Decimal("0"))

    def test_dos_creditos_no_cubren_si_valor_credito_sin_penalidad(self):
        """Sin pasar valor_credito del contexto, se asume 20 % off (bug histórico)."""
        monto_tarjeta, _, _ = validar_creditos_pago(
            self.usuario,
            self.actividad,
            2,
            2,
            Decimal("10000.00"),
            REGLA_SEGUNDA_QUINCENA,
        )
        self.assertEqual(monto_tarjeta, Decimal("2000.00"))
