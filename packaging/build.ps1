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
$updaterExecutable = Join-Path $distributionRoot "radar-scanner-updater.exe"
$bundleDirectory = Join-Path $distributionRoot "release-bundle"
$winSwVersion = "2.12.0"
$winSwUrl = "https://github.com/winsw/winsw/releases/download/v$winSwVersion/WinSW-x64.exe"
$winSwSha256 = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
$winSwDownload = Join-Path $env:TEMP "WinSW-x64-v$winSwVersion.exe"
$agentVersionFile = Join-Path $env:TEMP "radar-agent-version-info.txt"
$managerVersionFile = Join-Path $env:TEMP "radar-manager-version-info.txt"
$updaterVersionFile = Join-Path $env:TEMP "radar-updater-version-info.txt"
$brandIcon = Join-Path $repositoryRoot "logo\icon.ico"

function New-PyInstallerVersionFile(
    [string]$Path,
    [string]$FileDescription,
    [string]$OriginalFilename,
    [string]$Version,
    [int[]]$VersionTuple
) {
    $content = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($VersionTuple -join ', ')),
    prodvers=($($VersionTuple -join ', ')),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'VNPAY'),
          StringStruct(u'FileDescription', u'$FileDescription'),
          StringStruct(u'FileVersion', u'$Version'),
          StringStruct(u'InternalName', u'$OriginalFilename'),
          StringStruct(u'OriginalFilename', u'$OriginalFilename'),
          StringStruct(u'ProductName', u'VNPAY RADAR Scanner Agent'),
          StringStruct(u'ProductVersion', u'$Version')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
    [IO.File]::WriteAllText($Path, $content, [Text.UTF8Encoding]::new($false))
}

Push-Location $repositoryRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required to build the Agent package."
    }

    $version = (Select-String -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") `
        -Pattern '^version = "([^"]+)"$').Matches[0].Groups[1].Value
    if ($version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
        throw "Release version must use MAJOR.MINOR.PATCH format: $version"
    }
    $versionTuple = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], 0)
    $fileVersion = $versionTuple -join "."
    New-PyInstallerVersionFile $agentVersionFile `
        "VNPAY RADAR Scanner Agent Worker" "radar-scanner-agent.exe" `
        $version $versionTuple
    New-PyInstallerVersionFile $managerVersionFile `
        "VNPAY RADAR Scanner Manager" "radar-scanner-manager.exe" `
        $version $versionTuple
    New-PyInstallerVersionFile $updaterVersionFile `
        "VNPAY RADAR Scanner Updater" "radar-scanner-updater.exe" `
        $version $versionTuple
    $env:RADAR_AGENT_VERSION_FILE = $agentVersionFile
    $env:RADAR_MANAGER_VERSION_FILE = $managerVersionFile
    $env:RADAR_UPDATER_VERSION_FILE = $updaterVersionFile

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
    uv run pyinstaller --clean --noconfirm packaging/radar-scanner-updater.spec
    if ($LASTEXITCODE -ne 0) { throw "Updater PyInstaller build failed." }

    if (Test-Path -LiteralPath $bundleDirectory) {
        Remove-Item -LiteralPath $bundleDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $bundleDirectory -Force | Out-Null
    Copy-Item -LiteralPath $agentDirectory -Destination (Join-Path $bundleDirectory "agent") -Recurse
    Copy-Item -LiteralPath $managerExecutable -Destination $bundleDirectory
    Copy-Item -LiteralPath $updaterExecutable -Destination $bundleDirectory

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
    [IO.File]::WriteAllText(
        (Join-Path $bundleDirectory "VERSION"),
        "$version`n",
        [Text.UTF8Encoding]::new($false)
    )

    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    Get-ChildItem -LiteralPath $OutputDirectory -File | Where-Object {
        $_.Name -match '^VNPAYRadarScannerAgent-(Portable|Setup)-.*-x64\.(zip|exe)$' -or
        $_.Name -match '^VNPAYRadarScannerAgent-.*-SHA256SUMS\.txt$' -or
        $_.Name -match '^vnpay-radar-scanner-agent-.*-win-x64\.zip$'
    } | Remove-Item -Force
    $archive = Join-Path $OutputDirectory "VNPAYRadarScannerAgent-Portable-$version-x64.zip"
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
            "/WX" `
            "/DAPP_VERSION=$version" `
            "/DAPP_FILE_VERSION=$fileVersion" `
            "/DBRAND_ICON=$brandIcon" `
            "/DSOURCE_DIR=$bundleDirectory" `
            "/DOUTPUT_DIR=$OutputDirectory" `
            (Join-Path $PSScriptRoot "installer.nsi")
        if ($LASTEXITCODE -ne 0) { throw "NSIS installer build failed." }
        $installer = Join-Path $OutputDirectory "VNPAYRadarScannerAgent-Setup-$version-x64.exe"
        $installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
        Write-Output "Installer: $installer"
        Write-Output "Installer SHA256: $installerHash"
    }

    $checksumFile = Join-Path $OutputDirectory "VNPAYRadarScannerAgent-$version-SHA256SUMS.txt"
    $releaseArtifacts = Get-ChildItem -LiteralPath $OutputDirectory -File | Where-Object {
        $_.Name -in @(
            "VNPAYRadarScannerAgent-Portable-$version-x64.zip",
            "VNPAYRadarScannerAgent-Setup-$version-x64.exe"
        )
    } | Sort-Object Name
    $checksumLines = foreach ($artifact in $releaseArtifacts) {
        $hash = (Get-FileHash -LiteralPath $artifact.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($artifact.Name)"
    }
    [IO.File]::WriteAllLines(
        $checksumFile,
        $checksumLines,
        [Text.UTF8Encoding]::new($false)
    )
    Write-Output "Checksums: $checksumFile"
} finally {
    Remove-Item -LiteralPath $agentVersionFile, $managerVersionFile, $updaterVersionFile -Force `
        -ErrorAction SilentlyContinue
    Remove-Item Env:RADAR_AGENT_VERSION_FILE, Env:RADAR_MANAGER_VERSION_FILE, `
        Env:RADAR_UPDATER_VERSION_FILE `
        -ErrorAction SilentlyContinue
    Pop-Location
}
