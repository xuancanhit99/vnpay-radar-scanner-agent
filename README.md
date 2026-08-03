# VNPAY RADAR Scanner Agent

Windows edge worker that pulls APK scan jobs from RADAR and delegates them to the local
`apk-scan-api`. The MVP supports `TC-MOBI-3` and one concurrent job.

## Run in console

1. Start Docker Desktop and `apk-scan-api` on `127.0.0.1:8000`.
2. Connect and authorize the Android device with ADB.
3. Copy `.env.example` to `.env` and set the service-account client secret.
4. Run:

```powershell
uv sync
uv run radar-scanner-agent
```

Console mode accepts the client secret from local environment configuration. The Windows
Service installer removes the plaintext secret from the installed `.env` and stores it in a
machine-scoped DPAPI file that is readable only by LocalSystem and local Administrators.

Required Keycloak client configuration:

- Client ID `vnpay-radar-agent`, confidential client.
- Service account enabled; Standard, Implicit, and Direct Access Grants disabled.
- Client role `scanner-agent` assigned to the client's own service-account user.
- No `call-vnpay-sso-spi-service` or HR-sync role is required.

Local state defaults to `C:\ProgramData\VNPAY\RadarScannerAgent\agent.db`. SQLite is only an
outbox for results awaiting delivery; PostgreSQL in RADAR remains the source of truth.

## Build and install the Windows Service

Build the signed-input, unsigned-output development package from PowerShell:

```powershell
.\packaging\build.ps1
```

The build runs tests and Ruff, creates a PyInstaller `onedir` bundle, downloads pinned WinSW
`v2.12.0`, verifies its SHA-256 checksum, and writes the ZIP to `packaging/output/`.

Open PowerShell as Administrator and install from the unzipped package or build directory:

```powershell
.\install-service.ps1 -ConfigFile C:\path\to\vnpay-radar-scanner-agent\.env
```

Installed paths:

- Program: `C:\Program Files\VNPAY\Radar Scanner Agent`
- Config/state: `C:\ProgramData\VNPAY\RadarScannerAgent`
- Logs: `C:\ProgramData\VNPAY\RadarScannerAgent\logs`
- Service: `VNPAYRadarScannerAgent` with delayed automatic start and restart-on-failure

Operational checks:

```powershell
Get-Service VNPAYRadarScannerAgent
Restart-Service VNPAYRadarScannerAgent
Get-Content C:\ProgramData\VNPAY\RadarScannerAgent\logs\VNPAYRadarScannerAgent.err.log -Tail 100
```

The service runs as `LocalSystem`. The APK Scanner must continue listening only on
`127.0.0.1:8000`; Docker Desktop or the local Docker engine must be running for jobs to execute.

## API contract

The RADAR backend owns the scanner API contract:

- `POST /internal/scanner/agents/heartbeat`
- `POST /internal/scanner/jobs/claim`
- `POST /internal/scanner/jobs/{job_id}/start`
- `POST /internal/scanner/jobs/{job_id}/lease`
- `POST /internal/scanner/jobs/{job_id}/result`

Backend implementation and database migrations remain in
[`vnpay-radar-platform`](https://git.vnpay.vn/ansp/application-security/vnpay-radar-platform).
Agent and backend versions must be contract-tested together before release.
