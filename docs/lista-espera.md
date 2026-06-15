# Lista de espera con invitación por rol

Cuando un turno está lleno, los clientes pueden anotarse en su **lista de espera
sin cargo**. Al liberarse un cupo (cancelación o aumento de cupos), el sistema se
lo ofrece al siguiente candidato por mail, con prioridad para los **abonados de
esa actividad**.

## Cómo funciona

1. **Anotarse**: en el wizard de reserva, si el turno está completo, se ofrece
   anotarse en la lista de espera (sin pago). La reserva queda en estado
   `en_espera`.
2. **Liberación de cupo**: al cancelar una reserva confirmada (o al aumentar los
   cupos del turno), se elige el siguiente de la cola —primero los abonados de la
   actividad, luego los no abonados, ambos por orden de llegada— y se le crea una
   **invitación** (`InvitacionCupo`). Su reserva pasa a `invitado` y el cupo queda
   congelado mientras decide.
3. **Respuesta**: el candidato recibe un mail con la **hora límite** y un link a
   una página con el **contador en vivo**. Puede:
   - **Aceptar y pagar**: se lo lleva a pagar la clase; al aprobarse el pago, la
     reserva pasa a `confirmada`.
   - **Rechazar**: el cupo se le ofrece al siguiente.
   - **No responder**: cuando vence el plazo, la invitación caduca y el cupo pasa
     al siguiente.
4. **Aviso al admin**: cuando el total de clientes en lista de espera del sistema
   llega al umbral configurado, se les avisa por mail a los administradores.

## Configuración (`core/settings.py`)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `INVITACION_LISTA_ESPERA_MINUTOS` | `60` | Minutos que tiene el candidato para aceptar antes de que la invitación venza. |
| `UMBRAL_AVISO_LISTA_ESPERA` | `10` | Total de clientes en lista de espera que dispara el aviso al admin. |

Ambas se pueden sobreescribir con variables de entorno del mismo nombre.

## Expiración automática (Task Scheduler)

La expiración funciona de forma combinada:

- **Inmediata (lazy)**: cuando el cliente abre la página de la invitación o entra
  a "Mis reservas", si el plazo ya pasó se procesa al instante.
- **Garantizada (batch)**: un management command vence las invitaciones cuyo plazo
  pasó aunque nadie interactúe. Conviene correrlo cada 1 minuto.

```powershell
.venv\Scripts\python.exe manage.py procesar_invitaciones_vencidas
```

### Programarlo en Windows (cada 1 minuto)

```powershell
$accion = New-ScheduledTaskAction -Execute "C:\Users\ivann\Desktop\Proyecto_Club360\.venv\Scripts\python.exe" `
  -Argument "manage.py procesar_invitaciones_vencidas" `
  -WorkingDirectory "C:\Users\ivann\Desktop\Proyecto_Club360"
$disparador = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Club360 - Invitaciones vencidas" `
  -Action $accion -Trigger $disparador
```

> Si todavía no configuraste `EMAIL_HOST_USER` en el `.env`, los mails se imprimen
> en la consola (backend de consola) en lugar de enviarse de verdad.
