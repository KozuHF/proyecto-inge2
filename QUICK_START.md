# 🚀 QUICK START: Registrar Pago en Sede

## En 5 pasos

### 1️⃣ Crear Empleado (via Admin)

```
URL: http://127.0.0.1:8000/admin/
Usuarios > Agregar Usuario

Email: empleado@club.com
Nombre: Juan
Apellido: Test
DNI: 99999999
Fecha Nac: 01/01/1990
Contraseña: Test123!
Rol: EMPLOYEE ← IMPORTANTE

Click: Guardar
```

### 2️⃣ Loguearse

```
URL: http://127.0.0.1:8000/cuenta/login/

Email: empleado@club.com
Password: Test123!

Click: Ingresar
```

### 3️⃣ Ir al Panel

```
URL: http://127.0.0.1:8000/panel/

Ver en sidebar (izquierda):
- Turnos
- Registrar Pago en Sede ← CLICK AQUÍ
```

### 4️⃣ Buscar Cliente

```
Página: Buscar Reserva para Pago

Busca por:
- Nombre: "Juan" 
- DNI: "12345678"
- Email: "cliente@example.com"

Click: "Buscar"
```

### 5️⃣ Registrar Pago

```
Resultados: Ver lista de reservas

Para cada reserva:
- Cliente: Juan Test
- Turno: PADDLE mañana 14:00
- Saldo: $2.500

Click: "Registrar Pago"

Confirmación:
- Ver resumen
- Confirmar checkbox
- Click: "Confirmar Pago"

✅ ¡Pago registrado!
```

---

## 🧪 Ejecutar Tests

```bash
python manage.py test apps.pagos.tests.RegistrarPagoEfectivoTestCase -v 2
```

Esperado:
```
test_buscar_reservas_por_nombre ... ok
test_registrar_pago_efectivo_senado ... ok
test_no_puede_pagar_reserva_ya_pagada ... ok
test_no_puede_pagar_turno_vencido ... ok
test_monto_insuficiente ... ok
test_solo_empleado_puede_registrar_pago ... ok
test_pago_crea_registro_auditoria ... ok

Ran 7 tests in X.XXXs
OK ✅
```

---

## 📁 Archivos Clave

```
Búsqueda:
✅ /panel/buscar-reserva-pago/
   apps/pagos/templates/buscar_reserva_pago.html
   apps/accounts/views.py::buscar_reserva_para_pago()

Confirmación:
✅ /panel/registrar-pago/<id>/
   apps/pagos/templates/registrar_pago_efectivo.html
   apps/accounts/views.py::registrar_pago_efectivo()

Lógica:
✅ apps/pagos/services.py
   ├─ buscar_reservas_por_cliente()
   ├─ _validar_reserva_para_pago_efectivo()
   └─ registrar_pago_efectivo_empleado()

Tests:
✅ apps/pagos/tests.py
   └─ RegistrarPagoEfectivoTestCase (7 tests)
```

---

## ❌ Solución de Problemas

### No veo link "Registrar Pago"
```
✓ ¿Logueado como employee? (rol=EMPLOYEE)
✓ ¿Estás en /panel/?
✓ Si no, crear employee en /admin/
```

### Error 404 en búsqueda
```
✓ URL correcta: /panel/buscar-reserva-pago/
✓ Si no funciona, verificar core/urls.py tiene la ruta
```

### Tests fallan
```
✓ Ejecutar con: python manage.py test ... -v 2
✓ Ver mensaje de error específico
✓ Verificar Actividad.Nombre.PADDLE existe
```

### Pago rechazado
```
✓ Ver mensaje de error:
  - Reserva vencida
  - Ya pagada
  - Monto insuficiente
  - Turno pasado
```

---

## 📖 Documentación Completa

Archivos adicionales:
- `IMPLEMENTACION_COMPLETA.md` → Feature details
- `RESUMEN_FINAL.md` → Overview completo
- `plan.md` → Plan original

---

## 💡 Conceptos Clave

**SEÑADO**: Cliente pagó 50% (seña)
- Falta pagar: saldo restante (50%)
- Empleado ingresa ese monto

**PENDIENTE**: Cliente no pagó nada
- Falta pagar: monto total (100%)
- Empleado ingresa ese monto

**PAGADO**: Todo pagado
- ✅ Cliente listo para asistir
- ❌ No se puede registrar otro pago

---

*Listo para ir. ¿Preguntas? Ver IMPLEMENTACION_COMPLETA.md*
