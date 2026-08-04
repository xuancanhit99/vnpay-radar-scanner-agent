[CmdletBinding()]
param(
    [string]$InstallDirectory = "$env:ProgramFiles\VNPAY\Radar Scanner Agent",
    [string]$DataDirectory = "$env:ProgramData\VNPAY\RadarScannerAgent",
    [switch]$KeepProgramFiles,
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$serviceName = "VNPAYRadarScannerAgent"
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this uninstaller from an elevated PowerShell session."
}

function Wait-ServiceRemoval([string]$Name, [int]$TimeoutSeconds = 30) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (Get-Service -Name $Name -ErrorAction SilentlyContinue) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "Service $Name is still registered after $TimeoutSeconds seconds."
        }
        Start-Sleep -Milliseconds 500
    }
}

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne 'Stopped') {
    Stop-Service -Name $serviceName -Force
    (Get-Service -Name $serviceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
}

$wrapper = Join-Path $InstallDirectory "$serviceName.exe"
if ($service) {
    if (Test-Path -LiteralPath $wrapper) {
        & $wrapper uninstall
        if ($LASTEXITCODE -ne 0) { throw "WinSW service uninstall failed." }
    } else {
        & sc.exe delete $serviceName | Out-Null
        if ($LASTEXITCODE -notin @(0, 1060, 1072)) {
            throw "Could not delete stale service registration (sc.exe exit $LASTEXITCODE)."
        }
    }
    Wait-ServiceRemoval -Name $serviceName
}

if (-not $KeepProgramFiles -and (Test-Path -LiteralPath $InstallDirectory)) {
    Remove-Item -LiteralPath $InstallDirectory -Recurse -Force
}
if ($RemoveData -and (Test-Path -LiteralPath $DataDirectory)) {
    Remove-Item -LiteralPath $DataDirectory -Recurse -Force
}

Write-Output "Service removed. Data preserved: $(-not $RemoveData)"
