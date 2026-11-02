param([string]$CredentialFile = "$env:LOCALAPPDATA\LitMate\mysql-password.dpapi")
$ErrorActionPreference = 'Stop'
$projectPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not (Test-Path -LiteralPath $CredentialFile -PathType Leaf)) {
    throw 'Crea primero la credencial local DPAPI siguiendo docs/CONOCIMIENTO_CONTINUO.md.'
}
$protectedPassword = Get-Content -LiteralPath $CredentialFile | ConvertTo-SecureString
$passwordPointer = [IntPtr]::Zero
$previousPassword = $env:LITMATE_MYSQL_PASSWORD
Push-Location -LiteralPath $projectPath
try {
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($protectedPassword)
    $env:LITMATE_MYSQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    & (Join-Path $projectPath 'venv\Scripts\python.exe') -B -m scripts.knowledge.continuous_worker --non-interactive
    if ($LASTEXITCODE -ne 0) { throw 'El trabajador no terminó correctamente; revisa su informe local.' }
}
finally {
    $env:LITMATE_MYSQL_PASSWORD = $previousPassword
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $protectedPassword.Dispose()
    Pop-Location
}
