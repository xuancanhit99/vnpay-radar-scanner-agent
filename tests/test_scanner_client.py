import httpx
import pytest

from radar_agent.scanner_client import ScannerClient
from radar_agent.settings import AgentSettings


@pytest.mark.asyncio
async def test_heartbeat_uses_detected_device_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        return httpx.Response(
            200,
            json={
                "deviceModel": "Xiaomi 13",
                "usb": {"online": True, "serial": "314ebbfe"},
                "wifi": {"online": False, "serial": None},
            },
        )

    settings = AgentSettings(_env_file=None, scanner_url="http://scanner.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.3.2",
        )

    assert payload["device_status"] == "connected"
    assert payload["device_serial"] == "314ebbfe"
    assert payload["device_model"] == "Xiaomi 13"


@pytest.mark.asyncio
async def test_heartbeat_uses_configured_model_with_older_scanner_api() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        return httpx.Response(
            200,
            json={"usb": {"online": True, "serial": "device-001"}},
        )

    settings = AgentSettings(
        _env_file=None,
        scanner_url="http://scanner.local",
        device_model="Configured Device",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.3.2",
        )

    assert payload["device_model"] == "Configured Device"
