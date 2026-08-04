from typing import Any

import httpx

from radar_agent.models import JobResult, ScannerJob
from radar_agent.settings import AgentSettings

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


def _capability_status(
    testcase: dict[str, Any],
    *,
    scanner_status: str,
    device_payload: dict[str, Any],
) -> dict[str, Any]:
    device_type = testcase["device_type"]
    usb = device_payload.get("usb") or {}
    usb_online = bool(usb.get("online"))
    # Scanner API cũ chưa có cable_connected. USB ADB online vẫn là bằng chứng chắc
    # chắn cáp đang cắm; với adbhide ON, ADB chuyển sang Wi-Fi nhưng cable_connected
    # vẫn cho phép TC-MOBI-13 tự chuyển lại sang USB khi bắt đầu chạy.
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
    elif device_type == "main_usb" and not usb_cable_connected:
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


class ScannerClient:
    def __init__(self, settings: AgentSettings, client: httpx.AsyncClient):
        self._settings = settings
        self._client = client

    async def heartbeat_payload(self, *, hostname: str, version: str) -> dict[str, Any]:
        scanner_status = "unavailable"
        device_status = "disconnected"
        device_serial = None
        device_model = self._settings.device_model
        device_payload: dict[str, Any] = {}
        testcase_catalog = _LEGACY_TESTCASES
        try:
            health = await self._client.get(f"{self._settings.scanner_url}/health", timeout=5)
            health.raise_for_status()
            scanner_status = "busy" if health.json().get("busy") else "ready"

            device = await self._client.get(f"{self._settings.scanner_url}/device", timeout=20)
            device.raise_for_status()
            device_payload = device.json()
            usb = device_payload.get("usb") or {}
            wifi = device_payload.get("wifi") or {}
            selected = usb if usb.get("online") else wifi
            if selected.get("online"):
                device_status = "connected"
                device_serial = selected.get("serial")
                detected_model = str(device_payload.get("deviceModel") or "").strip()
                if detected_model:
                    device_model = detected_model
        except (httpx.HTTPError, ValueError):
            scanner_status = "unavailable"

        try:
            testcases = await self._client.get(f"{self._settings.scanner_url}/testcases", timeout=5)
            testcases.raise_for_status()
            testcase_catalog = _normalize_testcase_catalog(testcases.json())
        except (httpx.HTTPError, ValueError):
            testcase_catalog = _LEGACY_TESTCASES

        capability_statuses = [
            _capability_status(
                testcase,
                scanner_status=scanner_status,
                device_payload=device_payload,
            )
            for testcase in testcase_catalog
        ]

        return {
            "agent_id": self._settings.id,
            "display_name": self._settings.display_name,
            "hostname": hostname,
            "version": version,
            "scanner_status": scanner_status,
            "device_status": device_status,
            "device_serial": device_serial,
            "device_model": device_model,
            "capabilities": [item["testcase_id"] for item in capability_statuses],
            "capability_statuses": capability_statuses,
        }

    async def run_scan(self, job: ScannerJob) -> JobResult:
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
