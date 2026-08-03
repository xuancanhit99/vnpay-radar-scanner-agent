from typing import Any

import httpx

from radar_agent.models import JobResult, ScannerJob
from radar_agent.settings import AgentSettings


class ScannerClient:
    def __init__(self, settings: AgentSettings, client: httpx.AsyncClient):
        self._settings = settings
        self._client = client

    async def heartbeat_payload(self, *, hostname: str, version: str) -> dict[str, Any]:
        scanner_status = "unavailable"
        device_status = "disconnected"
        device_serial = None
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
        except (httpx.HTTPError, ValueError):
            scanner_status = "unavailable"

        return {
            "agent_id": self._settings.id,
            "display_name": self._settings.display_name,
            "hostname": hostname,
            "version": version,
            "scanner_status": scanner_status,
            "device_status": device_status,
            "device_serial": device_serial,
            "device_model": self._settings.device_model,
            "capabilities": ["TC-MOBI-3"],
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
