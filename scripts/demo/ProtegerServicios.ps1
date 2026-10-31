param([switch]$Aplicar)
$ErrorActionPreference = 'Stop'
$ruleName = 'LitMateDemo-InternalPorts-20261103'
$interfaces = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
    Where-Object { $_.NetworkInterfaceType -ne [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback } |
    ForEach-Object { $_.Name })
if ($interfaces.Count -eq 0) { throw 'No se identificaron interfaces; no se cambia el firewall.' }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $Aplicar) {
    [pscustomobject]@{ Rule = $ruleName; Action = 'Block inbound TCP on non-loopback interfaces';
        Ports = @(3306,33060,11434,8080); Interfaces = $interfaces; Administrator = $admin;
        Applied = $false } | ConvertTo-Json
    exit 0
}
if (-not $admin) { throw 'Ejecuta este script en PowerShell como administrador; no se ha cambiado nada.' }
if (@(Get-NetFirewallProfile | Where-Object { -not $_.Enabled }).Count -gt 0) {
    throw 'Existe un perfil de firewall desactivado. No se puede confirmar aislamiento con esta regla.'
}
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Description -ne 'Owned by LitMate demo 20261103') {
        throw 'El nombre pertenece a otra regla; no se modifica.'
    }
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Block -Profile Any -InterfaceAlias $interfaces
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName 'LitMate demo - servicios internos locales' `
        -Description 'Owned by LitMate demo 20261103' -Direction Inbound -Action Block -Enabled True `
        -Profile Any -Protocol TCP -LocalPort 3306,33060,11434,8080 -InterfaceAlias $interfaces | Out-Null
}
Get-NetFirewallRule -Name $ruleName | Select-Object Name,Enabled,Direction,Action | ConvertTo-Json
