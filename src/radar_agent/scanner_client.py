import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from radar_agent.device_identity import (
    DEFAULT_DEVICE_MODEL,
    normalize_device_model,
    resolve_adb_device_model,
)
from radar_agent.models import JobResult, ScannerJob
from radar_agent.settings import AgentSettings

_LOGGER = logging.getLogger(__name__)
DeviceModelResolver = Callable[[str], Awaitable[str | None]]

_LEGACY_TESTCASES = [
    {
        "sectionId": "TC-MOBI-3",
        "name": "Check Debugger",
        "device_type": "main",
        "timeout_seconds": 120,
    }
]
_LEGACY_DEVICE_TYPES = {
    "TC-MOBI-2": "main",
    "TC-MOBI-3": "main",
    "TC-MOBI-4": "emulator",
    "TC-MOBI-12": "main",
    "TC-MOBI-13": "main_usb",
}


def _normalize_testcase_catalog(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("testcases"), list):
        raise ValueError("Scanner testcase catalog is invalid")

    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload["testcases"]:
        if not isinstance(raw, dict):
            continue
        testcase_id = str(raw.get("sectionId") or "").strip()
        if not testcase_id or len(testcase_id) > 64 or testcase_id in seen:
            continue
        seen.add(testcase_id)
        device_type = str(
            raw.get("device_type") or _LEGACY_DEVICE_TYPES.get(testcase_id) or "unknown"
        )
        if device_type not in {"main", "main_usb", "emulator"}:
            continue
        try:
            timeout_seconds = max(1, min(900, int(raw.get("timeout_seconds") or 400)))
        except (TypeError, ValueError):
            timeout_seconds = 400
        name = str(raw.get("name") or "").strip()[:120] or testcase_id
        catalog.append(
            {
                "sectionId": testcase_id,
                "name": name,
                "device_type": device_type,
                "timeout_seconds": timeout_seconds,
            }
        )
    return catalog


def normalize_testcase_catalog(payload: Any) -> list[dict[str, Any]]:
    """Normalize the scanner catalog for callers that already own the probe lifecycle."""
    return _normalize_testcase_catalog(payload)


def default_testcase_catalog() -> list[dict[str, Any]]:
    return [dict(testcase) for testcase in _LEGACY_TESTCASES]


def _capability_status(
    testcase: dict[str, Any],
    *,
    scanner_status: str,
    device_payload: dict[str, Any],
) -> dict[str, Any]:
    device_type = testcase["device_type"]
    usb = device_payload.get("usb") or {}
    usb_online = bool(usb.get("online"))
    cable_status_available = "cable_connected" in usb
    # Scanner API main chưa có cable_connected. Khi đó chỉ precheck một kênh ADB đang
    # sống; chính POST /scan sẽ kiểm tra cáp trước khi tắt adbhide và chuyển sang USB.
    usb_cable_connected = usb_online or bool(usb.get("cable_connected"))
    wifi_online = bool((device_payload.get("wifi") or {}).get("online"))
    emulator_online = bool((device_payload.get("emulator") or {}).get("online"))

    if scanner_status == "unavailable":
        ready, reason = False, "APK Scanner không khả dụng"
    elif scanner_status == "busy":
        ready, reason = False, "APK Scanner đang chạy testcase khác"
    elif device_type == "main" and not (usb_online or wifi_online):
        ready, reason = False, "Thiết bị Android chưa kết nối qua USB hoặc Wi-Fi"
    elif device_type == "main_usb" and not (usb_online or wifi_online):
        ready, reason = False, "Thiết bị Android chưa kết nối qua USB hoặc Wi-Fi"
    elif device_type == "main_usb" and cable_status_available and not usb_cable_connected:
        ready, reason = False, "Testcase yêu cầu cáp USB đang kết nối"
    elif device_type == "emulator" and not emulator_online:
        ready, reason = False, "Testcase yêu cầu Android Emulator đang chạy"
    else:
        ready, reason = True, None

    return {
        "testcase_id": testcase["sectionId"],
        "name": testcase["name"],
        "device_type": device_type,
        "timeout_seconds": testcase["timeout_seconds"],
        "ready": ready,
        "reason": reason,
    }


def build_heartbeat_payload(
    settings: AgentSettings,
    *,
    hostname: str,
    version: str,
    scanner_status: str,
    device_payload: dict[str, Any],
    testcase_catalog: list[dict[str, Any]],
    device_model: str | None,
) -> dict[str, Any]:
    """Build the RADAR heartbeat from a completed scanner probe snapshot."""
    device_status = "disconnected"
    device_serial = None
    usb = device_payload.get("usb") or {}
    wifi = device_payload.get("wifi") or {}
    selected = usb if usb.get("online") else wifi
    if selected.get("online"):
        device_status = "connected"
        device_serial = selected.get("serial")

    capability_statuses = [
        _capability_status(
            testcase,
            scanner_status=scanner_status,
            device_payload=device_payload,
        )
        for testcase in testcase_catalog
    ]
    return {
        "agent_id": settings.id,
        "display_name": settings.display_name,
        "hostname": hostname,
        "version": version,
        "scanner_status": scanner_status,
        "device_status": device_status,
        "device_serial": device_serial,
        "device_model": normalize_device_model(device_model) or DEFAULT_DEVICE_MODEL,
        "capabilities": [item["testcase_id"] for item in capability_statuses],
        "capability_statuses": capability_statuses,
    }


class ScannerClient:
    def __init__(
        self,
        settings: AgentSettings,
        client: httpx.AsyncClient,
        *,
        device_model_resolver: DeviceModelResolver | None = None,
    ):
        self._settings = settings
        self._client = client
        self._device_model_resolver = device_model_resolver or resolve_adb_device_model
        self._probe_lock = asyncio.Lock()
        self._scan_in_progress = False
        self._last_device_payload: dict[str, Any] = {}
        self._last_testcase_catalog = list(_LEGACY_TESTCASES)
        self._device_models: dict[str, str] = {}

    async def _resolve_device_model(
        self,
        device_payload: dict[str, Any],
        *,
        scanner_status: str,
    ) -> str | None:
        usb = device_payload.get("usb") or {}
        wifi = device_payload.get("wifi") or {}
        selected = usb if usb.get("online") else wifi
        selected_serial = normalize_device_model(selected.get("serial"))
        identity = (
            normalize_device_model(device_payload.get("hardwareSerial")) or selected_serial
        )

        reported_model = normalize_device_model(device_payload.get("deviceModel"))
        if reported_model:
            if identity:
                self._device_models[identity] = reported_model
            return reported_model

        if identity and identity in self._device_models:
            return self._device_models[identity]
        if scanner_status == "busy" or not selected.get("online") or not selected_serial:
            return None

        try:
            detected_model = normalize_device_model(
                await self._device_model_resolver(selected_serial)
            )
        except Exception as exc:
            _LOGGER.debug(
                "Could not resolve Android model for ADB serial %s: %s",
                selected_serial,
                exc,
            )
            return None
        if detected_model:
            self._device_models[identity or selected_serial] = detected_model
        return detected_model

    async def heartbeat_payload(self, *, hostname: str, version: str) -> dict[str, Any]:
        scanner_status = "unavailable"
        device_payload = self._last_device_payload
        testcase_catalog = self._last_testcase_catalog
        try:
            health = await self._client.get(f"{self._settings.scanner_url}/health", timeout=5)
            health.raise_for_status()
            scanner_status = (
                "busy" if health.json().get("busy") or self._scan_in_progress else "ready"
            )

            # Some legacy scanner APIs make GET /device recover ADB Wi-Fi as a side effect.
            # During TC-MOBI-13 that would re-enable adbhide and disconnect the USB channel
            # while the testcase is still reading the device. Reuse the last stable snapshot
            # whenever a local scan is running.
            if scanner_status != "busy":
                async with self._probe_lock:
                    if self._scan_in_progress:
                        scanner_status = "busy"
                    else:
                        device = await self._client.get(
                            f"{self._settings.scanner_url}/device", timeout=20
                        )
                        device.raise_for_status()
                        device_payload = device.json()
                        self._last_device_payload = device_payload

                        try:
                            testcases = await self._client.get(
                                f"{self._settings.scanner_url}/testcases", timeout=5
                            )
                            testcases.raise_for_status()
                            testcase_catalog = _normalize_testcase_catalog(testcases.json())
                            self._last_testcase_catalog = testcase_catalog
                        except (httpx.HTTPError, ValueError):
                            testcase_catalog = self._last_testcase_catalog
        except (httpx.HTTPError, ValueError):
            scanner_status = "unavailable"

        device_model = await self._resolve_device_model(
            device_payload,
            scanner_status=scanner_status,
        )
        return build_heartbeat_payload(
            self._settings,
            hostname=hostname,
            version=version,
            scanner_status=scanner_status,
            device_payload=device_payload,
            testcase_catalog=testcase_catalog,
            device_model=device_model,
        )

    async def run_scan(self, job: ScannerJob) -> JobResult:
        async with self._probe_lock:
            self._scan_in_progress = True
        try:
            response = await self._client.post(
                f"{self._settings.scanner_url}/scan",
                json={"package_name": job.package_name, "sectionId": job.testcase_id},
                timeout=self._settings.scanner_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            result = str(payload.get("result") or "error").lower()
            if result not in {"pass", "fail", "warning", "error"}:
                result = "error"
            return JobResult(
                result=result,
                detail=str(payload.get("detail") or "Scanner không trả detail"),
                output=payload,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return JobResult(
                result="error",
                detail=f"Không gọi được APK Scanner local: {exc}",
                output={"error_type": type(exc).__name__},
            )
        finally:
            self._scan_in_progress = False
