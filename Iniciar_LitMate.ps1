$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$litmatePython = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
$litmateLauncher = Join-Path $PSScriptRoot 'reports\restauracion_publicada_20261111\arrancar_protegido.py'
$litmateStop = Join-Path $PSScriptRoot 'data\production\runtime\stop.request'

$litmateSocket = [System.Net.Sockets.TcpClient]::new()
$litmateOccupied = $false
try {
    $litmateSocket.Connect('127.0.0.1', 8003)
    $litmateOccupied = $true
} catch {
    $litmateOccupied = $false
} finally {
    $litmateSocket.Dispose()
}
if ($litmateOccupied) {
    Write-Host 'El puerto 8003 ya tiene una instancia. Comprueba https://xato.taila70665.ts.net/' -ForegroundColor Yellow
    return
}

# El lanzador de producción valida el puerto y toma su bloqueo antes de servir.
if (Test-Path -LiteralPath $litmateStop) {
    Move-Item -LiteralPath $litmateStop -Destination ($litmateStop + '.archivado-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
Write-Host 'LitMate se abrirá en https://xato.taila70665.ts.net/' -ForegroundColor Yellow
Write-Host 'Mantén esta terminal abierta. Ctrl+C detiene esta instancia.'
Write-Host 'El acceso reutiliza las credenciales DPAPI del usuario actual de Windows.'
& $litmatePython -B $litmateLauncher
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Comprueba si ya hay una instancia en 8003 y revisa el mensaje anterior.' -ForegroundColor Yellow
    exit $LASTEXITCODE
}
