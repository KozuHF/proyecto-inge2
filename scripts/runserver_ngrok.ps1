# ─────────────────────────────────────────────────────────────────────────────
#  runserver_ngrok.ps1
#
#  Levanta el túnel ngrok con tu dominio FIJO y arranca runserver. Los QR de
#  asistencia ya apuntan a esa dirección (SITE_BASE_URL en el .env), así que
#  el escáner integrado funciona desde el teléfono (que necesita HTTPS).
#
#  Requisitos:
#    - ngrok instalado y con authtoken configurado (ngrok config add-authtoken ...)
#    - En el .env:  SITE_BASE_URL=https://TU-DOMINIO.ngrok-free.dev
#
#  Uso:  powershell -ExecutionPolicy Bypass -File scripts\runserver_ngrok.ps1
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$port = 8000

# Dominio fijo: se toma de SITE_BASE_URL del .env (o de la variable de entorno).
$baseUrl = $env:SITE_BASE_URL
if (-not $baseUrl -and (Test-Path ".env")) {
    $linea = Select-String -Path ".env" -Pattern "^\s*SITE_BASE_URL\s*=\s*(.+)$" | Select-Object -First 1
    if ($linea) { $baseUrl = $linea.Matches[0].Groups[1].Value.Trim() }
}
if (-not $baseUrl) {
    Write-Error "No encontré SITE_BASE_URL (ni en el entorno ni en el .env)."
    exit 1
}
$dominio = $baseUrl -replace "^https?://", ""

# Ubicar ngrok (PATH o la carpeta donde lo instalamos).
$ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
if (-not $ngrok) { $ngrok = "$env:USERPROFILE\ngrok\ngrok.exe" }
if (-not (Test-Path $ngrok)) {
    Write-Error "No encontré ngrok. Instalalo o ajustá la ruta en el script."
    exit 1
}

Write-Host "Levantando túnel ngrok en https://$dominio ..." -ForegroundColor Cyan
$tunnel = Start-Process -FilePath $ngrok `
    -ArgumentList "http --url=https://$dominio $port" `
    -NoNewWindow -PassThru

Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Listo. Entrá por esta dirección (compu y teléfono):" -ForegroundColor Green
Write-Host "   https://$dominio" -ForegroundColor Yellow
Write-Host ""

try {
    & .\.venv\Scripts\python.exe manage.py runserver "0.0.0.0:$port"
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) {
        Write-Host "Cerrando túnel..." -ForegroundColor Cyan
        Stop-Process -Id $tunnel.Id -Force
    }
}
