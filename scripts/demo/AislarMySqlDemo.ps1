param([switch]$Aplicar, [switch]$Revertir)
# Preparado para autorización separada. Nunca actúa sobre el control remoto.
$ErrorActionPreference = 'Stop'
if ($Aplicar -and $Revertir) { throw 'Aplicar y revertir son operaciones excluyentes.' }
$ruleName = 'LitMateDemo-MySQL-Only-20261103'
$description = 'Owned by LitMate demo MySQL-only 20261103'
$service = Get-CimInstance Win32_Service -Filter "Name='MySQL80'"
if (-not $service -or $service.PathName -notmatch '^"([^"]+mysqld\.exe)"(?:\s|$)') {
    throw 'No se pudo verificar el ejecutable del servicio MySQL80.'
}
$program = [System.IO.Path]::GetFullPath($matches[1])
if (-not (Test-Path -LiteralPath $program -PathType Leaf)) { throw 'No existe el ejecutable MySQL verificado.' }
$interfaces = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
    Where-Object { $_.NetworkInterfaceType -ne [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback } |
    ForEach-Object { $_.Name })
if (-not $interfaces.Count) { throw 'No se identificaron interfaces; no se cambia nada.' }
$plan = [ordered]@{ Rule=$ruleName; Program=$program; Direction='Inbound'; Protocol='TCP';
    Ports=@(3306,33060); Profiles='Any'; Interfaces=$interfaces; ExcludesLoopback=$true;
    TouchesRemoteControlRules=$false; TouchesDockerRules=$false; TouchesTailscaleRules=$false;
    Applied=$false; Rollback='Disable only this owned rule with -Revertir' }
if (-not $Aplicar -and -not $Revertir) { $plan | ConvertTo-Json -Depth 4; exit 0 }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Requiere autorización y PowerShell como administrador; no se cambió ninguna regla.' }
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    $port = $existing | Get-NetFirewallPortFilter
    $app = $existing | Get-NetFirewallApplicationFilter
    if ($existing.Description -ne $description -or [string]$existing.Direction -ne 'Inbound' `
        -or [string]$existing.Action -ne 'Block' -or [string]$port.Protocol -notin @('TCP','6') `
        -or (@($port.LocalPort | Sort-Object { [int]$_ }) -join ',') -ne '3306,33060' -or $app.Program -ne $program) {
        throw 'La regla existente no coincide exactamente con el alcance propio; no se modifica.'
    }
}
if ($Revertir) {
    if ($existing) { Disable-NetFirewallRule -Name $ruleName | Out-Null }
    $plan.Reverted=$true
    $plan | ConvertTo-Json -Depth 4
    exit 0
}
if (@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count) {
    throw 'Un perfil de firewall está desactivado; no se aplica una protección incompleta.'
}
if ($existing) {
    # No alterar el alcance de una regla previa, aunque sea nuestra.
    Enable-NetFirewallRule -Name $ruleName | Out-Null
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName 'LitMate demo - MySQL local solamente' `
        -Description $description -Direction Inbound -Action Block -Enabled True -Profile Any `
        -Program $program -Protocol TCP -LocalPort 3306,33060 -InterfaceAlias $interfaces | Out-Null
}
$plan.Applied=$true
$plan | ConvertTo-Json -Depth 4
