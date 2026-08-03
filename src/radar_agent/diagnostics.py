import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any

import httpx

from radar_agent import __version__
from radar_agent.radar_client import RadarClient
from radar_agent.scanner_client import ScannerClient
from radar_agent.settings import AgentSettings
from radar_agent.token_provider import TokenProvider


@dataclass(frozen=True)
class DiagnosticResult:
    key: str
    label: str
    success: bool
    detail: str
    duration_ms: int


def _tls_verifier(verify_tls: bool) -> ssl.SSLContext | bool:
    return ssl.create_default_context() if verify_tls else False


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("error_description") or payload.get("detail") or "")
        except (ValueError, AttributeError):
            detail = ""
        suffix = f": {detail[:180]}" if detail else ""
        return f"HTTP {response.status_code}{suffix}"
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__}: {exc}"
    return str(exc) or type(exc).__name__


async def run_diagnostics(
    settings: AgentSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DiagnosticResult]:
    results: list[DiagnosticResult] = []
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(
        verify=_tls_verifier(settings.verify_tls),
        timeout=timeout,
        transport=transport,
    ) as client:
        token_provider = TokenProvider(settings, client)
        token_ready = False
        started = time.monotonic()
        try:
            await token_provider.get_token()
            token_ready = True
            results.append(
                DiagnosticResult(
                    "sso",
                    "VNPAY SSO",
                    True,
                    "Client credentials token issued",
                    int((time.monotonic() - started) * 1000),
                )
            )
        except Exception as exc:
            results.append(
                DiagnosticResult(
                    "sso",
                    "VNPAY SSO",
                    False,
                    _error_detail(exc),
                    int((time.monotonic() - started) * 1000),
                )
            )

        scanner = ScannerClient(settings, client)
        heartbeat_payload: dict[str, Any] | None = None
        started = time.monotonic()
        try:
            response = await client.get(f"{settings.scanner_url.rstrip('/')}/health", timeout=5)
            response.raise_for_status()
            payload = response.json()
            scanner_state = "busy" if payload.get("busy") else "ready"
            results.append(
                DiagnosticResult(
                    "scanner",
                    "APK Scanner",
                    True,
                    f"Local API is {scanner_state}",
                    int((time.monotonic() - started) * 1000),
                )
            )
        except Exception as exc:
            results.append(
                DiagnosticResult(
                    "scanner",
                    "APK Scanner",
                    False,
                    _error_detail(exc),
                    int((time.monotonic() - started) * 1000),
                )
            )

        started = time.monotonic()
        try:
            response = await client.get(f"{settings.scanner_url.rstrip('/')}/device", timeout=20)
            response.raise_for_status()
            payload = response.json()
            usb = payload.get("usb") or {}
            wifi = payload.get("wifi") or {}
            selected = usb if usb.get("online") else wifi
            if not selected.get("online"):
                raise RuntimeError("No authorized Android device detected")
            serial = selected.get("serial") or "unknown serial"
            results.append(
                DiagnosticResult(
                    "device",
                    "Android device",
                    True,
                    f"Connected: {serial}",
                    int((time.monotonic() - started) * 1000),
                )
            )
        except Exception as exc:
            results.append(
                DiagnosticResult(
                    "device",
                    "Android device",
                    False,
                    _error_detail(exc),
                    int((time.monotonic() - started) * 1000),
                )
            )

        if token_ready:
            started = time.monotonic()
            try:
                heartbeat_payload = await scanner.heartbeat_payload(
                    hostname=socket.gethostname(),
                    version=__version__,
                )
                radar = RadarClient(settings, client, token_provider)
                await radar.heartbeat(heartbeat_payload)
                results.append(
                    DiagnosticResult(
                        "radar",
                        "RADAR backend",
                        True,
                        "Authenticated heartbeat accepted",
                        int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                results.append(
                    DiagnosticResult(
                        "radar",
                        "RADAR backend",
                        False,
                        _error_detail(exc),
                        int((time.monotonic() - started) * 1000),
                    )
                )
        else:
            results.append(
                DiagnosticResult(
                    "radar",
                    "RADAR backend",
                    False,
                    "Skipped because SSO authentication failed",
                    0,
                )
            )

    return results
