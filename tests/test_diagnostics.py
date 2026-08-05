import json

import httpx
import pytest

from radar_agent.diagnostics import run_diagnostics
from radar_agent.settings import AgentSettings


@pytest.mark.asyncio
async def test_diagnostics_checks_sso_scanner_device_and_radar(tmp_path) -> None:
    requests: list[tuple[str, str]] = []
    events: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if str(request.url) == "https://sso.example/token":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 300})
        if str(request.url) == "http://scanner.local/health":
            return httpx.Response(200, json={"busy": False})
        if str(request.url) == "http://scanner.local/device":
            return httpx.Response(
                200,
                json={"usb": {"online": True, "serial": "xiaomi-001"}},
            )
        if str(request.url) == "http://scanner.local/testcases":
            return httpx.Response(
                200,
                json={
                    "testcases": [
                        {
                            "sectionId": "TC-MOBI-3",
                            "name": "Check Debugger",
                            "device_type": "main",
                            "timeout_seconds": 120,
                        }
                    ]
                },
            )
        if str(request.url) == "https://radar.example/internal/scanner/agents/heartbeat":
            assert request.headers["authorization"] == "Bearer token-1"
            heartbeat = json.loads(request.content)
            assert heartbeat["capabilities"] == ["TC-MOBI-3"]
            assert heartbeat["capability_statuses"][0]["ready"] is True
            return httpx.Response(200, json={"id": "windows-lab-02"})
        return httpx.Response(404)

    settings = AgentSettings(
        _env_file=None,
        base_url="https://radar.example",
        id="windows-lab-02",
        scanner_url="http://scanner.local",
        token_url="https://sso.example/token",
        client_secret="service-secret",
        database_path=tmp_path / "agent.db",
    )

    results = await run_diagnostics(
        settings,
        transport=httpx.MockTransport(handler),
        on_started=lambda key, _label: events.append(("started", key)),
        on_result=lambda result: events.append(("completed", result.key)),
    )

    assert [result.key for result in results] == ["sso", "scanner", "device", "radar"]
    assert all(result.success for result in results)
    assert len(requests) == 7
    assert events == [
        ("started", "sso"),
        ("completed", "sso"),
        ("started", "scanner"),
        ("completed", "scanner"),
        ("started", "device"),
        ("completed", "device"),
        ("started", "radar"),
        ("completed", "radar"),
    ]


@pytest.mark.asyncio
async def test_diagnostics_skip_radar_when_sso_fails(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://sso.example/token":
            return httpx.Response(401, json={"error_description": "invalid client"})
        if str(request.url).endswith("/health"):
            return httpx.Response(200, json={"busy": False})
        return httpx.Response(200, json={"usb": {"online": False}})

    settings = AgentSettings(
        _env_file=None,
        base_url="https://radar.example",
        scanner_url="http://scanner.local",
        token_url="https://sso.example/token",
        client_secret="invalid-secret",
        database_path=tmp_path / "agent.db",
    )

    results = await run_diagnostics(
        settings,
        transport=httpx.MockTransport(handler),
    )

    by_key = {result.key: result for result in results}
    assert by_key["sso"].success is False
    assert by_key["radar"].success is False
    assert "Skipped" in by_key["radar"].detail
    assert "invalid-secret" not in str(results)
