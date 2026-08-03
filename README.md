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

The client secret is only accepted from local environment configuration for the console MVP.
Before Windows Service rollout, move it to Windows Credential Manager or a DPAPI-protected file.

Required Keycloak client configuration:

- Client ID `vnpay-radar-agent`, confidential client.
- Service account enabled; Standard, Implicit, and Direct Access Grants disabled.
- Client role `scanner-agent` assigned to the client's own service-account user.
- No `call-vnpay-sso-spi-service` or HR-sync role is required.

Local state defaults to `C:\ProgramData\VNPAY\RadarScannerAgent\agent.db`. SQLite is only an
outbox for results awaiting delivery; PostgreSQL in RADAR remains the source of truth.

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
