param(
    [Parameter(Mandatory=$true)][string]$Origen,
    [int]$Puerto = 8010,
    [string]$Destino = 'reports\produccion_1_0_20261108\tareas'
)
$ErrorActionPreference = 'Stop'
$raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $raiz 'venv\Scripts\python.exe'
$cuentas = Join-Path $raiz 'data\accounts\users.sqlite3'
$runtime = Join-Path $raiz 'data\production\runtime'
$secreto = Join-Path $raiz 'data\production\mysql.dpapi'
$uri = [Uri]$Origen
if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.AbsolutePath -ne '/' -or $Puerto -eq 8003) { throw 'Origen o puerto no permitido.' }
$destinoAbsoluto = [IO.Path]::GetFullPath((Join-Path $raiz $Destino))
if (-not $destinoAbsoluto.StartsWith((Join-Path $raiz 'reports\'), [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $destinoAbsoluto)) { throw 'Utiliza una carpeta nueva bajo reports.' }
New-Item -ItemType Directory -Path $destinoAbsoluto | Out-Null
$usuario = [Security.Principal.WindowsIdentity]::GetCurrent().Name
function EscribirTarea([string]$Nombre, [string]$Argumentos, [string]$Disparador) {
    $escape = [Security.SecurityElement]
    $cmd = $escape::Escape($python); $argsXml = $escape::Escape($Argumentos)
    $wd = $escape::Escape($raiz); $userXml = $escape::Escape($usuario)
    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <RegistrationInfo><Description>LitMate: tarea preparada, no instalada por el generador.</Description></RegistrationInfo>
 <Triggers>$Disparador</Triggers>
 <Principals><Principal id="Author"><UserId>$userXml</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
 <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Enabled>true</Enabled></Settings>
 <Actions Context="Author"><Exec><Command>$cmd</Command><Arguments>$argsXml</Arguments><WorkingDirectory>$wd</WorkingDirectory></Exec></Actions>
</Task>
"@
    [IO.File]::WriteAllText((Join-Path $destinoAbsoluto ($Nombre + '.xml')), $xml, [Text.Encoding]::Unicode)
}
$inicio = (Get-Date).Date.AddDays(1).AddHours(10).ToString('yyyy-MM-ddTHH:mm:ss')
$disparador = "<CalendarTrigger><StartBoundary>$inicio</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>"
EscribirTarea 'LitMate-Respaldo' ('-B -m scripts.accounts.backup_job --database "' + $cuentas + '" --folder "' + (Join-Path $raiz 'backups\automatic') + '" --keep 14 --interval-hours 20') $disparador
EscribirTarea 'LitMate-Web' ('-B -m scripts.production.supervise --origin "' + $Origen + '" --port ' + $Puerto + ' --accounts-db "' + $cuentas + '" --runtime "' + $runtime + '" --mysql-secret-file "' + $secreto + '"') '<LogonTrigger><Enabled>true</Enabled></LogonTrigger>'
Write-Output 'Se crearon dos XML. No se registraron tareas, no se inició Waitress ni se cambió Tailscale.'
