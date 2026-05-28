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


# ── TESTS: Registrar Pago en Efectivo (Empleado) ──────────────────────────────

class RegistrarPagoEfectivoTestCase(TestCase):
    """Tests para registrar pago en efectivo en sede por empleado."""
    
    def setUp(self):
        """Configuración inicial: crear usuarios, actividades y reservas."""
        from apps.turnos.models import Turno, Reserva
        
        # Crear empleado
        self.empleado = Usuario.objects.create_user(
            email="empleado@test.com",
            nombre="Empleado",
            apellido="Test",
            nro_documento="11111111",
            fecha_nacimiento=date(1990, 1, 1),
            password="Password123!",
            rol=Roles.EMPLOYEE,
        )
        
        # Crear cliente
        self.cliente = Usuario.objects.create_user(
            email="cliente@test.com",
            nombre="Juan",
            apellido="Pérez",
            nro_documento="12345678",
            fecha_nacimiento=date(1995, 5, 15),
            password="Password123!",
            rol=Roles.USER,
        )
        
        # Crear actividad
        self.actividad = Actividad.objects.create(
            nombre=Actividad.Nombre.PADDLE,
            cupos=4,
            precio_turno=Decimal("5000.00"),
        )
        
        # Crear turno
        manana = timezone.now().date() + timedelta(days=1)
        self.turno = Turno.objects.create(
            actividad=self.actividad,
            fecha=manana,
            hora=14,
            cupos=4,
        )
    
    def test_buscar_reservas_por_nombre(self):
        """Buscar reserva por nombre del cliente."""
        from apps.pagos import services
        from apps.turnos.models import Reserva
        
        # Crear reserva SEÑADA (seña pagada)
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        resultados = services.buscar_reservas_por_cliente("Juan")
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].id, reserva.id)
    
    def test_registrar_pago_efectivo_senado(self):
        """Registrar pago en efectivo: cambiar SEÑADO → PAGADO."""
        from apps.pagos import services
        from apps.turnos.models import Reserva
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        resultado = services.registrar_pago_efectivo_empleado(
            self.empleado,
            reserva.id,
            Decimal("2500.00"),
        )
        
        self.assertTrue(resultado.exito)
        self.assertIsNotNone(resultado.pago)
        self.assertEqual(resultado.pago.estado, "aprobado")
        
        # Verificar que reserva se actualizó
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado_pago, Reserva.EstadoPago.PAGADO)
        self.assertEqual(reserva.precio_abonado, Decimal("5000.00"))
    
    def test_no_puede_pagar_reserva_ya_pagada(self):
        """Intentar pagar reserva ya PAGADA debe fallar."""
        from apps.pagos import services
        from apps.turnos.models import Reserva
        from django.core.exceptions import ValidationError
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.PAGADO,
            precio_abonado=Decimal("5000.00"),
        )
        
        with self.assertRaises(ValidationError) as ctx:
            services.registrar_pago_efectivo_empleado(
                self.empleado,
                reserva.id,
                Decimal("5000.00"),
            )
        self.assertIn("ya está pagada", str(ctx.exception))
    
    def test_no_puede_pagar_turno_vencido(self):
        """Intentar pagar turno vencido debe fallar."""
        from apps.pagos import services
        from apps.turnos.models import Reserva, Turno
        from django.core.exceptions import ValidationError
        
        ayer = timezone.now().date() - timedelta(days=1)
        turno_vencido = Turno.objects.create(
            actividad=self.actividad,
            fecha=ayer,
            hora=14,
            cupos=4,
        )
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=turno_vencido,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        with self.assertRaises(ValidationError) as ctx:
            services.registrar_pago_efectivo_empleado(
                self.empleado,
                reserva.id,
                Decimal("2500.00"),
            )
        self.assertIn("vencido", str(ctx.exception))
    
    def test_monto_insuficiente(self):
        """Monto menor a lo adeudado debe fallar."""
        from apps.pagos import services
        from apps.turnos.models import Reserva
        from django.core.exceptions import ValidationError
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        with self.assertRaises(ValidationError) as ctx:
            services.registrar_pago_efectivo_empleado(
                self.empleado,
                reserva.id,
                Decimal("1000.00"),  # Menos que el saldo
            )
        self.assertIn("insuficiente", str(ctx.exception))
    
    def test_solo_empleado_puede_registrar_pago(self):
        """Solo usuario con rol EMPLOYEE puede registrar pago."""
        from apps.pagos import services
        from apps.turnos.models import Reserva
        from django.core.exceptions import ValidationError
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        # Intentar con cliente (rol USER)
        with self.assertRaises(ValidationError) as ctx:
            services.registrar_pago_efectivo_empleado(
                self.cliente,
                reserva.id,
                Decimal("2500.00"),
            )
        self.assertIn("empleados", str(ctx.exception))
    
    def test_pago_crea_registro_auditoria(self):
        """Verificar que se crea registro Pago con usuario correcto."""
        from apps.pagos import services
        from apps.pagos.models import Pago
        from apps.turnos.models import Reserva
        
        reserva = Reserva.objects.create(
            usuario=self.cliente,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            estado_pago=Reserva.EstadoPago.SENADO,
            precio_abonado=Decimal("2500.00"),
        )
        
        resultado = services.registrar_pago_efectivo_empleado(
            self.empleado,
            reserva.id,
            Decimal("2500.00"),
        )
        
        # Verificar registro Pago
        pago = Pago.objects.get(pk=resultado.pago.id)
        self.assertEqual(pago.usuario, self.empleado)  # Usuario es el empleado
        self.assertEqual(pago.reserva, reserva)
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)
        self.assertEqual(pago.tipo_cobro, Pago.TipoCobro.SALDO)
        self.assertTrue(pago.referencia.startswith("PAY-"))
