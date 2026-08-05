[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "output")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Version) {
    $Version = (Select-String -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") `
        -Pattern '^version = "([^\"]+)"$').Matches[0].Groups[1].Value
}
Assert-Condition ($Version -match '^\d+\.\d+\.\d+$') "Invalid release version: $Version"

$setupName = "VNPAYRadarScannerAgent-Setup-$Version-x64.exe"
$portableName = "VNPAYRadarScannerAgent-Portable-$Version-x64.zip"
$checksumName = "VNPAYRadarScannerAgent-$Version-SHA256SUMS.txt"
$setupPath = Join-Path $OutputDirectory $setupName
$portablePath = Join-Path $OutputDirectory $portableName
$checksumPath = Join-Path $OutputDirectory $checksumName

foreach ($path in @($setupPath, $portablePath, $checksumPath)) {
    Assert-Condition (Test-Path -LiteralPath $path -PathType Leaf) "Missing release artifact: $path"
}

$expectedHashes = @{}
foreach ($line in Get-Content -LiteralPath $checksumPath) {
    Assert-Condition ($line -match '^([0-9a-f]{64})  (.+)$') "Invalid checksum line: $line"
    $expectedHashes[$Matches[2]] = $Matches[1]
}
Assert-Condition ($expectedHashes.Count -eq 2) "Checksum file must contain exactly 2 artifacts."
foreach ($artifact in @($setupPath, $portablePath)) {
    $name = Split-Path -Leaf $artifact
    Assert-Condition $expectedHashes.ContainsKey($name) "Missing checksum for $name"
    $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-Condition ($actual -eq $expectedHashes[$name]) "SHA-256 mismatch for $name"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($portablePath)
try {
    $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
    $requiredEntries = @(
        ".env.example",
        "install-service.ps1",
        "uninstall-service.ps1",
        "VERSION",
        "VNPAYRadarScannerAgent.exe",
        "agent/radar-scanner-agent.exe",
        "radar-scanner-manager.exe",
        "radar-scanner-updater.exe"
    )
    foreach ($entry in $requiredEntries) {
        Assert-Condition ($entry -in $entryNames) "Portable package is missing $entry"
    }
    $forbidden = @($entryNames | Where-Object {
        $_ -match '(^|/)\.env$' -or
        $_ -match '(^|/)client-secret\.dpapi$' -or
        $_ -match '\.(db|sqlite|sqlite3|log)$'
    })
    Assert-Condition ($forbidden.Count -eq 0) `
        "Portable package contains private runtime files: $($forbidden -join ', ')"
} finally {
    $archive.Dispose()
}

$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) `
    "radar-agent-release-$([guid]::NewGuid().ToString('N'))"
try {
    Expand-Archive -LiteralPath $portablePath -DestinationPath $temporaryDirectory
    $packagedVersion = (Get-Content -LiteralPath `
        (Join-Path $temporaryDirectory "VERSION") -Raw).Trim()
    Assert-Condition ($packagedVersion -eq $Version) `
        "Portable VERSION is $packagedVersion, expected $Version"

    $exampleConfig = Get-Content -LiteralPath `
        (Join-Path $temporaryDirectory ".env.example") -Raw
    Assert-Condition ($exampleConfig -notmatch '(?m)^RADAR_AGENT_CLIENT_SECRET=\S+') `
        ".env.example contains a non-empty client secret."

    $versionedFiles = @(
        (Join-Path $temporaryDirectory "agent\radar-scanner-agent.exe"),
        (Join-Path $temporaryDirectory "radar-scanner-manager.exe"),
        (Join-Path $temporaryDirectory "radar-scanner-updater.exe"),
        $setupPath
    )
    foreach ($file in $versionedFiles) {
        $metadata = (Get-Item -LiteralPath $file).VersionInfo
        Assert-Condition ($metadata.ProductVersion -eq $Version) `
            "ProductVersion for $file is $($metadata.ProductVersion), expected $Version"
        Assert-Condition ($metadata.FileVersion -eq $Version) `
            "FileVersion for $file is $($metadata.FileVersion), expected $Version"
    }
} finally {
    if (Test-Path -LiteralPath $temporaryDirectory) {
        Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
    }
}

$signatureStatus = (Get-AuthenticodeSignature -LiteralPath $setupPath).Status
Write-Output "Release $Version verified successfully. Authenticode: $signatureStatus"
