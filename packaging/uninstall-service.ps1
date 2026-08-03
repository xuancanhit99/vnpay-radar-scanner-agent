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

$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne 'Stopped') {
    Stop-Service -Name $serviceName -Force
    (Get-Service -Name $serviceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
}

$wrapper = Join-Path $InstallDirectory "$serviceName.exe"
if ($service -and (Test-Path -LiteralPath $wrapper)) {
    & $wrapper uninstall
    if ($LASTEXITCODE -ne 0) { throw "WinSW service uninstall failed." }
}

if (-not $KeepProgramFiles -and (Test-Path -LiteralPath $InstallDirectory)) {
    Remove-Item -LiteralPath $InstallDirectory -Recurse -Force
}
if ($RemoveData -and (Test-Path -LiteralPath $DataDirectory)) {
    Remove-Item -LiteralPath $DataDirectory -Recurse -Force
}

Write-Output "Service removed. Data preserved: $(-not $RemoveData)"
