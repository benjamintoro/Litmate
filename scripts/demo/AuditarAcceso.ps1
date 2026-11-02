param([string]$Salida = '')
# Auditoría de sólo lectura, sin elevar permisos ni modificar redes/reglas.
$ErrorActionPreference = 'Stop'
if ($Salida -and (Test-Path -LiteralPath $Salida)) { throw 'El informe ya existe.' }
$tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
$status = & $tailscale status --json | ConvertFrom-Json
$raw = (netsh advfirewall firewall show rule name=all verbose) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el firewall mediante netsh.' }
$rules = @()
foreach ($block in ($raw -split '(?m)(?=^Nombre de regla:|^Rule Name:)')) {
    if ($block -notmatch '(?im)^(?:Nombre de regla:|Rule Name:).*(?:mysql|ollama|tailscale|docker|chrome remote|LitMateDemo)' `
        -and $block -notmatch '(?im)^\s*LocalPort:\s*(3306|33060|11434|8080)\s*$') { continue }
    $fields = [ordered]@{}
    foreach ($line in ($block -split "`n")) {
        if ($line -match '^\s*(Nombre de regla|Rule Name|Habilitada|Enabled|Direcci.n|Direction|Acci.n|Action|Perfiles|Profiles|LocalPort|RemotePort|Protocolo|Protocol)\s*:\s*(.*)$') {
            $fields[$matches[1]] = $matches[2].Trim()
        }
    }
    $rules += $fields
}
$listeners = @()
foreach ($line in @(netstat -ano)) {
    if ($line -match '^\s*TCP\s+(\S+):(3306|33060|11434|8080|8000|8002|8003)\s+\S+\s+(?:LISTENING|ESCUCHANDO)\s+(\d+)\s*$') {
        $listeners += [pscustomobject]@{ Address = $matches[1]; Port = [int]$matches[2]; PID = [int]$matches[3] }
    }
}
$report = [ordered]@{
    ReadOnly = $true
    Tailscale = [ordered]@{ State=$status.BackendState; DNS=$status.Self.DNSName;
        MagicDNS=$status.CurrentTailnet.MagicDNSEnabled; CertificateDomains=$status.CertDomains;
        FunnelCapabilityAdvertised=($null -ne $status.Self.CapMap.'https://tailscale.com/cap/funnel');
        Serve=(& $tailscale serve status --json | ConvertFrom-Json);
        Funnel=(& $tailscale funnel status --json | ConvertFrom-Json) }
    FirewallProfiles=@(Get-NetFirewallProfile | ForEach-Object {
        [pscustomobject]@{ Name=$_.Name; Enabled=[bool]$_.Enabled }
    })
    FirewallPolicy=@(netsh advfirewall show allprofiles | Where-Object { $_ -match 'BlockInbound|AllowOutbound' })
    RelevantRules=$rules
    Listeners=$listeners
    RemoteProcesses=@(Get-Process | Where-Object { $_.ProcessName -match 'tailscale|remoting_host|remoting_desktop|anydesk|rustdesk|teamviewer' } |
        Select-Object -ExpandProperty ProcessName -Unique)
    DockerPorts=@(docker port litmate-searxng-1)
    ChangedFirewall=$false
    ChangedTailscale=$false
}
$json = $report | ConvertTo-Json -Depth 8
if ($Salida) {
    $absolute = [System.IO.Path]::GetFullPath($Salida)
    $parent = [System.IO.Path]::GetDirectoryName($absolute)
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    [System.IO.File]::WriteAllText($absolute, $json, (New-Object System.Text.UTF8Encoding($false)))
}
$json
