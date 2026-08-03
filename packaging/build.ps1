[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "output"),
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distributionRoot = Join-Path $repositoryRoot "dist"
$agentDirectory = Join-Path $distributionRoot "radar-scanner-agent"
$managerExecutable = Join-Path $distributionRoot "radar-scanner-manager.exe"
$bundleDirectory = Join-Path $distributionRoot "release-bundle"
$winSwVersion = "2.12.0"
$winSwUrl = "https://github.com/winsw/winsw/releases/download/v$winSwVersion/WinSW-x64.exe"
$winSwSha256 = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
$winSwDownload = Join-Path $env:TEMP "WinSW-x64-v$winSwVersion.exe"

Push-Location $repositoryRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required to build the Agent package."
    }

    uv sync --group dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }

    if (-not $SkipTests) {
        uv run pytest -q
        if ($LASTEXITCODE -ne 0) { throw "Agent tests failed." }
        uv run ruff check src tests
        if ($LASTEXITCODE -ne 0) { throw "Agent lint failed." }
    }

    uv run pyinstaller --clean --noconfirm packaging/radar-scanner-agent.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    uv run pyinstaller --clean --noconfirm packaging/radar-scanner-manager.spec
    if ($LASTEXITCODE -ne 0) { throw "Manager PyInstaller build failed." }

    if (Test-Path -LiteralPath $bundleDirectory) {
        Remove-Item -LiteralPath $bundleDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $bundleDirectory -Force | Out-Null
    Copy-Item -LiteralPath $agentDirectory -Destination (Join-Path $bundleDirectory "agent") -Recurse
    Copy-Item -LiteralPath $managerExecutable -Destination $bundleDirectory

    if (-not (Test-Path -LiteralPath $winSwDownload)) {
        Invoke-WebRequest -Uri $winSwUrl -OutFile $winSwDownload
    }
    $actualHash = (Get-FileHash -LiteralPath $winSwDownload -Algorithm SHA256).Hash
    if ($actualHash -ne $winSwSha256) {
        throw "WinSW checksum mismatch: expected $winSwSha256, got $actualHash."
    }

    Copy-Item -LiteralPath $winSwDownload `
        -Destination (Join-Path $bundleDirectory "VNPAYRadarScannerAgent.exe") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install-service.ps1") `
        -Destination $bundleDirectory -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall-service.ps1") `
        -Destination $bundleDirectory -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot ".env.example") `
        -Destination $bundleDirectory -Force
    Copy-Item -LiteralPath (Join-Path $repositoryRoot "README.md") `
        -Destination $bundleDirectory -Force

    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $version = (Select-String -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") `
        -Pattern '^version = "([^"]+)"$').Matches[0].Groups[1].Value
    $archive = Join-Path $OutputDirectory "VNPAYRadarScannerAgent-Portable-$version-x64.zip"
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    Compress-Archive -Path (Join-Path $bundleDirectory "*") -DestinationPath $archive

    $archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    Write-Output "Portable package: $archive"
    Write-Output "Portable SHA256: $archiveHash"

    if (-not $SkipInstaller) {
        $makeNsis = Get-Command makensis.exe -ErrorAction SilentlyContinue
        $makeNsisPath = if ($makeNsis) { $makeNsis.Source } else { $null }
        if (-not $makeNsis) {
            $commonNsis = Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"
            if (Test-Path -LiteralPath $commonNsis) {
                $makeNsisPath = $commonNsis
            }
        }
        if (-not $makeNsisPath) {
            throw "NSIS is required to build Setup.exe. Install package NSIS.NSIS with winget."
        }
        & $makeNsisPath `
            "/DAPP_VERSION=$version" `
            "/DSOURCE_DIR=$bundleDirectory" `
            "/DOUTPUT_DIR=$OutputDirectory" `
            (Join-Path $PSScriptRoot "installer.nsi")
        if ($LASTEXITCODE -ne 0) { throw "NSIS installer build failed." }
        $installer = Join-Path $OutputDirectory "VNPAYRadarScannerAgent-Setup-$version-x64.exe"
        $installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
        Write-Output "Installer: $installer"
        Write-Output "Installer SHA256: $installerHash"
    }
} finally {
    Pop-Location
}
