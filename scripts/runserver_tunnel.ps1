# ─────────────────────────────────────────────────────────────────────────────
#  runserver_tunnel.ps1
#
#  Levanta un túnel HTTPS con cloudflared, captura la URL pública que genera,
#  se la pasa a Django (SITE_BASE_URL) y arranca runserver. Así los QR de
#  asistencia siempre apuntan a la dirección del túnel y se pueden escanear
#  con el escáner integrado desde el teléfono (que necesita HTTPS).
#
#  Requisitos: cloudflared instalado (https://github.com/cloudflare/cloudflared).
#  Uso:        powershell -ExecutionPolicy Bypass -File scripts\runserver_tunnel.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$port = 8000
$logFile = Join-Path $env:TEMP "club360_cloudflared.log"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Error "cloudflared no está instalado. Instalalo con 'winget install Cloudflare.cloudflared' y volvé a intentar."
    exit 1
}

if (Test-Path $logFile) { Remove-Item $logFile -Force }

Write-Host "Iniciando túnel cloudflared..." -ForegroundColor Cyan
$tunnel = Start-Process -FilePath "cloudflared" `
    -ArgumentList "tunnel --url http://localhost:$port" `
    -RedirectStandardError $logFile -RedirectStandardOutput "$logFile.out" `
    -NoNewWindow -PassThru

# Esperar a que cloudflared imprima la URL pública
$url = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $logFile) {
        $match = Select-String -Path $logFile -Pattern "https://[-a-z0-9]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) { $url = $match.Matches[0].Value; break }
    }
}

if (-not $url) {
    Write-Error "No se pudo obtener la URL del túnel. Revisá $logFile"
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    exit 1
}

Write-Host ""
Write-Host "Túnel listo. Entrá por esta dirección (compu y teléfono):" -ForegroundColor Green
Write-Host "   $url" -ForegroundColor Yellow
Write-Host ""

$env:SITE_BASE_URL = $url
try {
    & .\.venv\Scripts\python.exe manage.py runserver "0.0.0.0:$port"
}
finally {
    # Al cortar el server (Ctrl+C), bajamos también el túnel.
    if ($tunnel -and -not $tunnel.HasExited) {
        Write-Host "Cerrando túnel..." -ForegroundColor Cyan
        Stop-Process -Id $tunnel.Id -Force
    }
}
