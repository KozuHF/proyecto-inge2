# Asistencia por QR — Guía de uso

Esta funcionalidad permite tomar **asistencia a las clases mediante un código QR**.
Cada vez que un cliente paga **por completo** una clase, se le genera un QR único.
El empleado lo escanea y queda registrada la asistencia.

---

## 1. ¿Cómo funciona? (resumen)

- **Cliente:** entra a *Mis reservas* y, en cada clase **confirmada y pagada por
  completo**, ve un botón **"Ver QR"**.
- **Empleado/Admin:** desde el *Panel → Escanear asistencia*, usa la cámara para
  leer el QR del cliente (o abre el link del QR) y confirma la asistencia.
- **Regla horaria:** la asistencia solo se puede registrar **desde 30 minutos
  antes de que empiece la clase hasta que la clase termina** (los turnos duran 1 h).
- Una vez que **pasó la clase**, el QR **deja de mostrarse** y la reserva pasa al
  **Historial de clases** (con el resultado: *Presente* / *Ausente*).

---

## 2. Puesta en marcha (una sola vez)

Desde la raíz del proyecto (`Proyecto_Club360`):

```bash
# 1. Traer la rama y actualizar
git fetch
git checkout feat/asistencia-qr      # o 'dev' si ya se mergeó
git pull

# 2. Activar el entorno virtual (Windows)
.venv\Scripts\activate

# 3. Instalar dependencias (incluye 'segno', la librería del QR)
pip install -r requirements.txt

# 4. Actualizar la base de datos (crea la tabla de asistencia)
python manage.py migrate

# 5. Cargar datos de prueba (cliente, empleado y una clase de HOY ya pagada)
python manage.py seed_asistencia
```

El comando `seed_asistencia` imprime las credenciales y los links. Lo podés
volver a correr con `--reset` para regenerar una clase fresca a la hora actual:

```bash
python manage.py seed_asistencia --reset
```

### Credenciales de prueba

| Rol | Email | Contraseña |
|-----|-------|------------|
| Cliente | `qr_cliente@test.com` | `Cliente123!` |
| Empleado | `qr_empleado@test.com` | `Empleado123!` |

---

## 3. Probar en la computadora (lo más simple)

```bash
python manage.py runserver
```

Abrí `http://localhost:8000/` y:

1. **Como cliente** (`qr_cliente@test.com`): andá a *Mis reservas* → **Ver QR**.
2. **Como empleado** (en otra ventana / modo incógnito): *Panel → Escanear
   asistencia*. La página usa la **webcam** (funciona en `localhost`). Mostrale
   el QR del cliente a la cámara.
3. ¿No tenés webcam? Copiá el **link de marcado** que imprimió el seed y abrilo
   logueado como empleado → **Confirmar asistencia**.

> ⏰ Si te dice *"Fuera de horario"*, es la regla de la ventana de 30 min. Corré
> `python manage.py seed_asistencia --reset` para tener una clase a la hora actual.

---

## 4. Probar desde el celular (con cámara integrada)

Para usar el **escáner de cámara dentro de la app desde el teléfono** se necesita
**HTTPS** (los navegadores no dan permiso de cámara por `http://`). La forma más
fácil es un túnel **ngrok** con dominio fijo y gratuito.

> Cada persona usa **su propia cuenta de ngrok** (el dominio fijo es 1 por cuenta).

### 4.1 Crear tu túnel ngrok (una sola vez)

1. **Crear cuenta** (gratis): https://dashboard.ngrok.com/signup y **verificá tu
   email** (sin verificar, el túnel no arranca).
2. **Copiar tu authtoken:** https://dashboard.ngrok.com/get-started/your-authtoken
3. **Reclamar tu dominio fijo:** https://dashboard.ngrok.com/domains → **"+ New
   Domain"** → te da uno tipo `algo-algo-1234.ngrok-free.dev`.
4. **Instalar ngrok:**
   - Con winget: `winget install ngrok.ngrok`
   - O bajándolo de https://ngrok.com/download (descomprimís el `.exe`).
5. **Configurar tu authtoken:**
   ```bash
   ngrok config add-authtoken TU_AUTHTOKEN
   ```

### 4.2 Configurar el proyecto

En el archivo **`.env`** de la raíz (crealo si no existe; **no se sube al repo**),
agregá tu dominio:

```
SITE_BASE_URL=https://TU-DOMINIO.ngrok-free.dev
```

Esto hace que **todos los QR apunten siempre a esa dirección**, sin importar por
dónde entres. (También deja el CSRF configurado para que el "Confirmar
asistencia" funcione por el túnel.)

### 4.3 Levantar todo

Opción A — script todo en uno (levanta túnel + server):
```bash
powershell -ExecutionPolicy Bypass -File scripts\runserver_ngrok.ps1
```

Opción B — manual, en dos terminales:
```bash
# Terminal 1
ngrok http --url=https://TU-DOMINIO.ngrok-free.dev 8000
# Terminal 2
python manage.py runserver 0.0.0.0:8000
```

### 4.4 Usarlo

1. **En la compu**, abrí `https://TU-DOMINIO.ngrok-free.dev/` (por la URL del
   túnel, **no** `localhost`). Entrá como **cliente** → *Mis reservas* → **Ver QR**.
2. **En el teléfono** (anda con wifi o datos), abrí la misma URL del túnel. Entrá
   como **empleado** → *Panel → Escanear asistencia*.
3. Apuntá la cámara al QR de la pantalla → **Confirmar asistencia**. ✅

> La primera vez, ngrok muestra una pantalla de advertencia: tocá **"Visit Site"**.

---

## 5. Detalle de las reglas

- **El QR solo aparece** para clases **confirmadas** y **pagadas por completo**
  (las señadas o pendientes no tienen QR todavía).
- **Ventana de marcado:** desde 30 min antes del inicio hasta el fin de la clase.
  Fuera de eso, el sistema responde *"Fuera de horario"*.
- **Seguridad:** marcar asistencia exige sesión de **empleado o admin**. Un
  cliente no puede auto-marcarse (le da error 403). El código del QR es un UUID
  imposible de adivinar.
- **No se duplica:** si dos empleados escanean el mismo QR a la vez, queda
  registrado una sola vez (el segundo ve *"ya registrada"*).
- **Historial:** cuando la clase termina, la reserva sale de *Próximas* y aparece
  en *Mis reservas → Ver historial de clases*, con badge **Presente** / **Ausente**.

---

## 6. Problemas frecuentes

| Síntoma | Causa / Solución |
|---------|------------------|
| *"Fuera de horario"* al marcar | La clase no está en su ventana. Corré `seed_asistencia --reset` para una clase a la hora actual. |
| El teléfono no puede abrir el QR | El QR se generó entrando por `localhost`. Entrá por la URL del túnel (o configurá `SITE_BASE_URL`). |
| La cámara no abre en el teléfono | Falta HTTPS. Usá el túnel ngrok (por `http://IP` el navegador bloquea la cámara). |
| `ERR_NGROK_382` | Tenés que **verificar tu email** en https://dashboard.ngrok.com/user/settings. |
| 403 al "Confirmar asistencia" por el túnel | Asegurate de tener `SITE_BASE_URL` con tu dominio en el `.env` (configura el CSRF solo). |
| No aparece "Ver QR" | La reserva no está confirmada+pagada por completo, o la clase ya pasó (mirá el Historial). |
| `ModuleNotFoundError: segno` | Faltó `pip install -r requirements.txt`. |

---

## 7. Dónde está cada cosa (para devs)

- App: `apps/asistencia/` (modelo `Asistencia`, `services.py`, `qr.py`, vistas).
- Reglas de negocio: `apps/asistencia/services.py` (`ventana_asistencia`,
  `marcar_asistencia`, `qr_disponible`).
- Pantallas del cliente: botón "Ver QR" en `apps/turnos/templates/turnos/mis_reservas.html`;
  historial en `historial_clases.html`.
- Pantallas del empleado: `apps/asistencia/templates/asistencia/` (escanear,
  marcar, resultado).
- Datos de prueba: `apps/asistencia/management/commands/seed_asistencia.py`.
