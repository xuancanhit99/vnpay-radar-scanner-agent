[CmdletBinding()]
param(
    [string]$PackageDirectory = $PSScriptRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigFile,
    [string]$InstallDirectory = "$env:ProgramFiles\VNPAY\Radar Scanner Agent",
    [string]$DataDirectory = "$env:ProgramData\VNPAY\RadarScannerAgent",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$serviceName = "VNPAYRadarScannerAgent"
$installingUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from an elevated PowerShell session."
}

function Read-DotEnv([string]$Path) {
    $values = [System.Collections.Generic.Dictionary[string, string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([^=\s]+)\s*=\s*(.*)$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$name] = $value
    }
    return $values
}

$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$sourceConfig = (Resolve-Path -LiteralPath $ConfigFile).Path
$coreExecutable = Join-Path $package "radar-scanner-agent.exe"
$wrapperSource = Join-Path $package "$serviceName.exe"
if (-not (Test-Path -LiteralPath $coreExecutable)) { throw "Missing $coreExecutable" }
if (-not (Test-Path -LiteralPath $wrapperSource)) { throw "Missing $wrapperSource" }

$config = Read-DotEnv $sourceConfig
$clientSecret = $config['RADAR_AGENT_CLIENT_SECRET']
if ([string]::IsNullOrWhiteSpace($clientSecret)) {
    throw "RADAR_AGENT_CLIENT_SECRET is missing from $sourceConfig"
}

$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existingService) {
    if ($existingService.Status -ne 'Stopped') {
        Stop-Service -Name $serviceName -Force
        (Get-Service -Name $serviceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    }
    $existingWrapper = Join-Path $InstallDirectory "$serviceName.exe"
    if (Test-Path -LiteralPath $existingWrapper) {
        & $existingWrapper uninstall
        if ($LASTEXITCODE -ne 0) { throw "Could not uninstall the existing service." }
    }
}

New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
$logDirectory = Join-Path $DataDirectory "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Copy-Item -Path (Join-Path $package "*") -Destination $InstallDirectory -Recurse -Force

$secretFile = Join-Path $DataDirectory "client-secret.dpapi"
$secretBytes = [Text.Encoding]::UTF8.GetBytes($clientSecret)
try {
    $protectedBytes = [Security.Cryptography.ProtectedData]::Protect(
        $secretBytes,
        $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    [IO.File]::WriteAllBytes($secretFile, $protectedBytes)
} finally {
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)
}

$serviceConfig = [System.Collections.Generic.List[string]]::new()
foreach ($entry in $config.GetEnumerator() | Sort-Object Key) {
    if ($entry.Key -in @(
        'RADAR_AGENT_CLIENT_SECRET',
        'RADAR_AGENT_CLIENT_SECRET_FILE',
        'RADAR_AGENT_DATABASE_PATH'
    )) { continue }
    $serviceConfig.Add("$($entry.Key)=$($entry.Value)")
}
$serviceConfig.Add("RADAR_AGENT_CLIENT_SECRET_FILE=$($secretFile.Replace('\', '/'))")
$databaseFile = Join-Path $DataDirectory "agent.db"
$serviceConfig.Add("RADAR_AGENT_DATABASE_PATH=$($databaseFile.Replace('\', '/'))")
$installedEnv = Join-Path $DataDirectory ".env"
[IO.File]::WriteAllLines($installedEnv, $serviceConfig, [Text.UTF8Encoding]::new($false))

$escapedDataDirectory = [Security.SecurityElement]::Escape($DataDirectory)
$escapedLogDirectory = [Security.SecurityElement]::Escape($logDirectory)
$xml = @"
<service>
  <id>$serviceName</id>
  <name>VNPAY RADAR Scanner Agent</name>
  <description>Pulls APK scan jobs from VNPAY RADAR and executes them through the local APK Scanner.</description>
  <executable>%BASE%\radar-scanner-agent.exe</executable>
  <workingdirectory>$escapedDataDirectory</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <onfailure action="restart" delay="10 sec" />
  <resetfailure>1 hour</resetfailure>
  <stoptimeout>30 sec</stoptimeout>
  <logpath>$escapedLogDirectory</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
"@
$installedXml = Join-Path $InstallDirectory "$serviceName.xml"
[IO.File]::WriteAllText($installedXml, $xml, [Text.UTF8Encoding]::new($false))

& icacls $DataDirectory /inheritance:r `
    /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' `
    "*$($installingUserSid):(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not secure $DataDirectory" }
& icacls $logDirectory /grant:r "*$($installingUserSid):(OI)(CI)R" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not grant log read access." }
& icacls $secretFile /inheritance:r `
    /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not secure the DPAPI secret file." }

$wrapper = Join-Path $InstallDirectory "$serviceName.exe"
& $wrapper install
if ($LASTEXITCODE -ne 0) { throw "WinSW service installation failed." }

if (-not $NoStart) {
    Start-Service -Name $serviceName
    (Get-Service -Name $serviceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
}

Get-Service -Name $serviceName | Select-Object Name, Status, StartType
Write-Output "Config: $installedEnv"
Write-Output "Logs: $(Join-Path $DataDirectory 'logs')"
