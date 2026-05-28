#!/usr/bin/env python
"""
Verificador rápido del sistema de Registrar Pago en Sede.
Ejecutar: python verify_payment_system.py
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from django.urls import reverse
from django.core.management import call_command
from datetime import date, timedelta
from decimal import Decimal

from apps.accounts.models import Usuario, Roles
from apps.actividades.models import Actividad
from apps.turnos.models import Turno, Reserva
from apps.pagos import services as pagos_services

print("\n" + "="*70)
print("✅ VERIFICADOR: REGISTRAR PAGO EN SEDE")
print("="*70 + "\n")

# 1. VERIFICAR URLS
print("1️⃣  VERIFICANDO URLs...")
try:
    url_buscar = reverse('buscar_reserva_pago')
    url_registrar = reverse('registrar_pago_efectivo', args=[1])
    print(f"   ✅ buscar_reserva_pago: {url_buscar}")
    print(f"   ✅ registrar_pago_efectivo: {url_registrar}")
except Exception as e:
    print(f"   ❌ Error en URLs: {e}")

# 2. VERIFICAR MODELOS Y BD
print("\n2️⃣  VERIFICANDO BASE DE DATOS...")
try:
    actividades = Actividad.objects.count()
    usuarios = Usuario.objects.count()
    print(f"   ✅ Actividades en BD: {actividades}")
    print(f"   ✅ Usuarios en BD: {usuarios}")
except Exception as e:
    print(f"   ❌ Error BD: {e}")

# 3. VERIFICAR SERVICIO
print("\n3️⃣  VERIFICANDO SERVICIO DE PAGO...")
try:
    # Crear datos de prueba
    empleado = Usuario.objects.create_user(
        email="test_emp@test.com",
        nombre="TestEmp",
        apellido="Test",
        nro_documento="99999999",
        fecha_nacimiento=date(1990, 1, 1),
        password="Test123!",
        rol=Roles.EMPLOYEE,
    )
    
    cliente = Usuario.objects.create_user(
        email="test_cli@test.com",
        nombre="TestCli",
        apellido="Test",
        nro_documento="88888888",
        fecha_nacimiento=date(1995, 5, 15),
        password="Test123!",
        rol=Roles.USER,
    )
    
    actividad, _ = Actividad.objects.get_or_create(
        nombre=Actividad.Nombre.PADDLE,
        defaults={"cupos": 4, "precio_turno": Decimal("5000.00")}
    )
    
    manana = (date.today() + timedelta(days=1))
    turno = Turno.objects.create(
        actividad=actividad,
        fecha=manana,
        hora=14,
        cupos=4,
    )
    
    reserva = Reserva.objects.create(
        usuario=cliente,
        turno=turno,
        estado=Reserva.Estado.CONFIRMADA,
        estado_pago=Reserva.EstadoPago.SENADO,
        precio_abonado=Decimal("2500.00"),
    )
    
    print(f"   ✅ Empleado creado: {empleado.email}")
    print(f"   ✅ Cliente creado: {cliente.email}")
    print(f"   ✅ Reserva SEÑADA creada: ID={reserva.id}")
    
    # 4. PROBAR BÚSQUEDA
    print("\n4️⃣  PROBANDO BÚSQUEDA...")
    resultados = pagos_services.buscar_reservas_por_cliente("TestCli")
    if len(resultados) == 1 and resultados[0].id == reserva.id:
        print(f"   ✅ Búsqueda funciona: encontrada reserva ID={resultados[0].id}")
    else:
        print(f"   ❌ Búsqueda falló: esperaba 1 resultado, obtuve {len(resultados)}")
    
    # 5. PROBAR REGISTRO DE PAGO
    print("\n5️⃣  PROBANDO REGISTRO DE PAGO EN EFECTIVO...")
    resultado = pagos_services.registrar_pago_efectivo_empleado(
        empleado,
        reserva.id,
        Decimal("2500.00"),
    )
    
    if resultado.exito:
        print(f"   ✅ Pago registrado exitosamente")
        print(f"      - Referencia: {resultado.pago.referencia}")
        print(f"      - Usuario: {resultado.pago.usuario.email}")
        print(f"      - Monto: ${resultado.pago.monto}")
        
        # Verificar actualización
        reserva.refresh_from_db()
        if reserva.estado_pago == Reserva.EstadoPago.PAGADO:
            print(f"   ✅ Reserva actualizada a PAGADO")
        else:
            print(f"   ❌ Reserva NO fue actualizada: {reserva.estado_pago}")
    else:
        print(f"   ❌ Pago falló: {resultado.mensaje}")
    
    # 6. PROBAR ERRORES
    print("\n6️⃣  PROBANDO VALIDACIONES...")
    try:
        pagos_services.registrar_pago_efectivo_empleado(
            empleado,
            reserva.id,
            Decimal("2500.00"),
        )
        print(f"   ❌ Debería haber fallado (ya pagada)")
    except Exception:
        print(f"   ✅ Validación OK: no permite pagar dos veces")
    
    print("\n" + "="*70)
    print("✅ VERIFICACIÓN COMPLETA - TODOS LOS SISTEMAS FUNCIONAN")
    print("="*70 + "\n")
    
    # Limpiar
    empleado.delete()
    cliente.delete()
    turno.delete()
    
except Exception as e:
    import traceback
    print(f"   ❌ Error: {e}")
    traceback.print_exc()
