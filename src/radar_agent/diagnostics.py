import asyncio
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from radar_agent.radar_client import RadarClient
from radar_agent.settings import AgentSettings
from radar_agent.token_provider import TokenProvider


@dataclass(frozen=True)
class DiagnosticResult:
    key: str
    label: str
    success: bool
    detail: str
    duration_ms: int


DiagnosticStarted = Callable[[str, str], None]
DiagnosticCompleted = Callable[[DiagnosticResult], None]
_RESULT_ORDER = {key: index for index, key in enumerate(("sso", "scanner", "device", "radar"))}


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
    on_started: DiagnosticStarted | None = None,
    on_result: DiagnosticCompleted | None = None,
) -> list[DiagnosticResult]:
    results: list[DiagnosticResult] = []

    def notify_started(key: str, label: str) -> None:
        if on_started:
            on_started(key, label)

    def completed(result: DiagnosticResult) -> None:
        results.append(result)
        if on_result:
            on_result(result)

    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(
        verify=_tls_verifier(settings.verify_tls),
        timeout=timeout,
        transport=transport,
    ) as client:
        token_provider = TokenProvider(settings, client)
        scanner_url = settings.scanner_url.rstrip("/")

        async def check_sso() -> bool:
            notify_started("sso", "VNPAY SSO")
            started = time.monotonic()
            try:
                await token_provider.get_token()
                completed(
                    DiagnosticResult(
                        "sso",
                        "VNPAY SSO",
                        True,
                        "Client credentials token issued",
                        int((time.monotonic() - started) * 1000),
                    )
                )
                return True
            except Exception as exc:
                completed(
                    DiagnosticResult(
                        "sso",
                        "VNPAY SSO",
                        False,
                        _error_detail(exc),
                        int((time.monotonic() - started) * 1000),
                    )
                )
                return False

        async def check_device() -> dict[str, Any]:
            notify_started("device", "Android device")
            started = time.monotonic()
            payload: dict[str, Any] = {}
            try:
                response = await client.get(f"{scanner_url}/device", timeout=20)
                response.raise_for_status()
                payload = response.json()
                usb = payload.get("usb") or {}
                wifi = payload.get("wifi") or {}
                selected = usb if usb.get("online") else wifi
                if not selected.get("online"):
                    raise RuntimeError("No authorized Android device detected")
                serial = selected.get("serial") or "unknown serial"
                completed(
                    DiagnosticResult(
                        "device",
                        "Android device",
                        True,
                        f"Connected: {serial}",
                        int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                completed(
                    DiagnosticResult(
                        "device",
                        "Android device",
                        False,
                        _error_detail(exc),
                        int((time.monotonic() - started) * 1000),
                    )
                )
            return payload

        async def check_scanner() -> None:
            notify_started("scanner", "APK Scanner")
            started = time.monotonic()
            scanner_status = "unavailable"
            try:
                response = await client.get(f"{scanner_url}/health", timeout=5)
                response.raise_for_status()
                scanner_status = "busy" if response.json().get("busy") else "ready"
                completed(
                    DiagnosticResult(
                        "scanner",
                        "APK Scanner",
                        True,
                        f"Local API is {scanner_status}",
                        int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                completed(
                    DiagnosticResult(
                        "scanner",
                        "APK Scanner",
                        False,
                        _error_detail(exc),
                        int((time.monotonic() - started) * 1000),
                    )
                )

            if scanner_status != "ready":
                notify_started("device", "Android device")
                reason = (
                    "Skipped while APK Scanner is busy"
                    if scanner_status == "busy"
                    else "Skipped because APK Scanner is unavailable"
                )
                completed(
                    DiagnosticResult(
                        "device",
                        "Android device",
                        False,
                        reason,
                        0,
                    )
                )
                return

            await check_device()

        async def check_radar(token_task: asyncio.Task[bool]) -> None:
            notify_started("radar", "RADAR backend")
            started = time.monotonic()
            token_ready = await token_task
            if not token_ready:
                completed(
                    DiagnosticResult(
                        "radar",
                        "RADAR backend",
                        False,
                        "Skipped because SSO authentication failed",
                        int((time.monotonic() - started) * 1000),
                    )
                )
                return
            try:
                radar = RadarClient(settings, client, token_provider)
                await radar.health()
                completed(
                    DiagnosticResult(
                        "radar",
                        "RADAR backend",
                        True,
                        "Authenticated health check passed",
                        int((time.monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:
                completed(
                    DiagnosticResult(
                        "radar",
                        "RADAR backend",
                        False,
                        _error_detail(exc),
                        int((time.monotonic() - started) * 1000),
                    )
                )

        token_task = asyncio.create_task(check_sso())
        await asyncio.gather(token_task, check_scanner(), check_radar(token_task))

    return sorted(results, key=lambda result: _RESULT_ORDER[result.key])
