$ErrorActionPreference = 'Stop'
$mysql = Get-Service -Name MySQL80 -ErrorAction SilentlyContinue
$ports = @()
foreach ($port in @(3306,11434,8080,8002,8003)) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.BeginConnect('127.0.0.1',$port,$null,$null)
        $open = $connection.AsyncWaitHandle.WaitOne(1500) -and $client.Connected
        $ports += [pscustomobject]@{ Port = $port; LocalConnection = $open }
    } finally { $client.Close() }
}
$report = [ordered]@{ MySQL = if ($mysql) { [string]$mysql.Status } else { 'Not found' };
    Ports = $ports; Docker = @(docker ps --format '{{.Names}} {{.Status}} {{.Ports}}') }
$tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (Test-Path -LiteralPath $tailscale) {
    $status = & $tailscale status --json | ConvertFrom-Json
    $report.Tailscale = [ordered]@{ State = $status.BackendState; DNS = $status.Self.DNSName;
        Funnel = (& $tailscale funnel status --json | ConvertFrom-Json) }
}
$report | ConvertTo-Json -Depth 8
