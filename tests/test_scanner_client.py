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
    assert payload["capabilities"] == ["TC-MOBI-3"]


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


@pytest.mark.asyncio
async def test_heartbeat_advertises_dynamic_testcases_with_readiness() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "deviceModel": "Xiaomi 13",
                    "usb": {
                        "online": True,
                        "serial": "314ebbfe",
                        "cable_connected": True,
                    },
                    "wifi": {"online": False, "serial": None},
                    "emulator": {"online": False, "serial": "emulator-5554"},
                },
            )
        if request.url.path == "/testcases":
            return httpx.Response(
                200,
                json={
                    "testcases": [
                        {
                            "sectionId": "TC-MOBI-3",
                            "name": "Check Debugger",
                            "device_type": "main",
                            "timeout_seconds": 120,
                        },
                        {
                            "sectionId": "TC-MOBI-4",
                            "name": "Check Emulator",
                            "device_type": "emulator",
                            "timeout_seconds": 300,
                        },
                        {
                            "sectionId": "TC-MOBI-13",
                            "name": "Check USB Debug",
                            "device_type": "main_usb",
                            "timeout_seconds": 360,
                        },
                    ]
                },
            )
        return httpx.Response(404)

    settings = AgentSettings(_env_file=None, scanner_url="http://scanner.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.5.0",
        )

    assert payload["capabilities"] == ["TC-MOBI-3", "TC-MOBI-4", "TC-MOBI-13"]
    statuses = {item["testcase_id"]: item for item in payload["capability_statuses"]}
    assert statuses["TC-MOBI-3"]["ready"] is True
    assert statuses["TC-MOBI-13"]["ready"] is True
    assert statuses["TC-MOBI-4"]["ready"] is False
    assert "Emulator" in statuses["TC-MOBI-4"]["reason"]


@pytest.mark.asyncio
async def test_heartbeat_requires_physical_cable_for_usb_debug_testcase() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "usb": {
                        "online": False,
                        "serial": None,
                        "cable_connected": False,
                    },
                    "wifi": {"online": True, "serial": "192.0.2.10:5555"},
                    "emulator": {"online": False, "serial": "emulator-5554"},
                },
            )
        if request.url.path == "/testcases":
            return httpx.Response(
                200,
                json={
                    "testcases": [
                        {
                            "sectionId": "TC-MOBI-13",
                            "name": "Check USB Debug",
                            "device_type": "main_usb",
                            "timeout_seconds": 360,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    settings = AgentSettings(_env_file=None, scanner_url="http://scanner.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.5.0",
        )

    status = payload["capability_statuses"][0]
    assert status["ready"] is False
    assert status["reason"] == "Testcase yêu cầu cáp USB đang kết nối"


@pytest.mark.asyncio
async def test_heartbeat_allows_usb_debug_testcase_over_wifi_when_cable_is_connected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "usb": {
                        "online": False,
                        "serial": "314ebbfe",
                        "cable_connected": True,
                    },
                    "wifi": {"online": True, "serial": "192.0.2.10:5555"},
                    "emulator": {"online": False, "serial": "emulator-5554"},
                },
            )
        if request.url.path == "/testcases":
            return httpx.Response(
                200,
                json={
                    "testcases": [
                        {
                            "sectionId": "TC-MOBI-13",
                            "name": "Check USB Debug",
                            "device_type": "main_usb",
                            "timeout_seconds": 360,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    settings = AgentSettings(_env_file=None, scanner_url="http://scanner.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.5.2",
        )

    status = payload["capability_statuses"][0]
    assert payload["device_status"] == "connected"
    assert payload["device_serial"] == "192.0.2.10:5555"
    assert status["ready"] is True
    assert status["reason"] is None


@pytest.mark.asyncio
async def test_heartbeat_allows_usb_debug_with_legacy_scanner_over_wifi() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"busy": False})
        if request.url.path == "/device":
            return httpx.Response(
                200,
                json={
                    "usb": {"online": False, "serial": "314ebbfe"},
                    "wifi": {"online": True, "serial": "192.168.137.198:5555"},
                    "emulator": {"online": False, "serial": "emulator-5554"},
                },
            )
        if request.url.path == "/testcases":
            return httpx.Response(
                200,
                json={
                    "testcases": [
                        {
                            "sectionId": "TC-MOBI-13",
                            "name": "Check USB Debug",
                            "device": "314ebbfe",
                            "timeout_seconds": 360,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    settings = AgentSettings(_env_file=None, scanner_url="http://scanner.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await ScannerClient(settings, client).heartbeat_payload(
            hostname="WINDOWS-LAB",
            version="0.5.3",
        )

    status = payload["capability_statuses"][0]
    assert payload["device_status"] == "connected"
    assert payload["device_serial"] == "192.168.137.198:5555"
    assert status["device_type"] == "main_usb"
    assert status["ready"] is True
    assert status["reason"] is None
