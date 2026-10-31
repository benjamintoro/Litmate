param([string]$Salida = '')
# Solo lectura: contrasta reglas activas con condiciones que netsh no muestra,
# como PFN (familia de paquete). No interpreta permisos de Store como globales.
$ErrorActionPreference = 'Stop'
if ($Salida -and (Test-Path -LiteralPath $Salida)) { throw 'El informe ya existe.' }
$registry = Get-Item -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules'
$active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Enabled True -Direction Inbound)
$candidates = @()
$unresolved = @()
$packageRules = 0
foreach ($rule in $active) {
    $raw = $registry.GetValue($rule.Name)
    if (-not $raw) { $unresolved += $rule.Name; continue }
    $fields = @{}
    foreach ($part in ($raw -split '\|')) {
        $pair = $part -split '=',2
        if ($pair.Count -ne 2) { continue }
        if ($fields.ContainsKey($pair[0])) { $fields[$pair[0]] += @($pair[1]) }
        else { $fields[$pair[0]] = @($pair[1]) }
    }
    if ($fields.ContainsKey('PFN') -and $fields.PFN[0]) { $packageRules++; continue }
    $app = if ($fields.ContainsKey('App')) { [Environment]::ExpandEnvironmentVariables($fields.App[0]) } else { '' }
    $service = if ($fields.ContainsKey('Svc')) { $fields.Svc[0] } else { '' }
    if ($app -and $app -notmatch '(?i)mysqld\.exe$') { continue }
    if ($service -and $service -notin @('*','MySQL80')) { continue }
    $protocol = if ($fields.ContainsKey('Protocol')) { $fields.Protocol[0] } else { '256' }
    if ($protocol -notin @('6','256')) { continue }
    $ports = if ($fields.ContainsKey('LPort')) { $fields.LPort -join ',' } else { '*' }
    $matchesPorts = $ports -eq '*'
    foreach ($range in ($ports -split ',')) {
        if ($range.Trim() -match '^(\d+)(?:-(\d+))?$') {
            $low=[int]$matches[1]; $high=if($matches[2]){[int]$matches[2]}else{$low}
            if ((3306 -ge $low -and 3306 -le $high) -or (33060 -ge $low -and 33060 -le $high)) { $matchesPorts=$true }
        }
    }
    if (-not $matchesPorts) { continue }
    $candidates += [pscustomobject]@{ Name=$rule.DisplayName; RuleId=$rule.Name;
        Action=[string]$rule.Action; Profiles=[string]$rule.Profile; Program=$app; Service=$service;
        LocalPorts=$ports; LocalIPv4=@($fields.LA4); LocalIPv6=@($fields.LA6);
        RemoteIPv4=@($fields.RA4); RemoteIPv6=@($fields.RA6);
        HasLocalUserCondition=$fields.ContainsKey('LUAuth');
        PackageRestricted=$false }
}
$policy = New-Object -ComObject HNetCfg.FwPolicy2
$profiles = foreach($profile in @(1,2,4)) {
    [pscustomobject]@{Profile=$profile; Enabled=$policy.FirewallEnabled($profile);
        DefaultInbound=if($policy.DefaultInboundAction($profile) -eq 0){'Block'}else{'Allow'}}
}
$report = [ordered]@{ReadOnly=$true;ActiveInboundRules=$active.Count;Profiles=$profiles;
    PackagedApplicationRulesExcluded=$packageRules;MySQLCandidates=$candidates;
    UnresolvedActiveRuleIds=$unresolved;ExternalConnectivityTested=$false;
    FirewallChanged=$false;RouterConfigurationRead=$false}
$json = $report | ConvertTo-Json -Depth 7
if($Salida){
    $file=[System.IO.Path]::GetFullPath($Salida)
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($file)) | Out-Null
    [System.IO.File]::WriteAllText($file,$json,(New-Object System.Text.UTF8Encoding($false)))
}
$json
