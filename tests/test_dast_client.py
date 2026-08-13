import asyncio
import json
from pathlib import Path

import httpx
import pytest

from radar_agent.dast_client import DastScannerClient
from radar_agent.models import ScannerJob
from radar_agent.outbox import ResultOutbox
from radar_agent.settings import AgentSettings


class FakeRadarClient:
    async def get_dast_config(self, job_id: str, lease_token: str) -> dict:
        assert job_id == "job-1"
        assert lease_token == "lease-token"
        return {
            "base_url": "https://api.example.test",
            "principals": {"admin_user": {"token": "real-token"}},
            "auth": {
                "inject": [
                    {
                        "type": "header",
                        "field": "Authorization",
                        "format": "Bearer {token}",
                    }
                ]
            },
            "proxy": {"enabled": False},
        }

    async def get_dast_collection(self, job_id: str, lease_token: str) -> dict:
        assert job_id == "job-1"
        assert lease_token == "lease-token"
        return {"info": {"name": "Test"}, "item": []}


def _settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        id="windows-lab-01-dast",
        display_name="Windows Lab 01 DAST",
        dast_enabled=True,
        dast_engine_url="http://dast.local",
        dast_engine_api_key="engine-key",
        dast_poll_interval_seconds=1,
        database_path=tmp_path / "agent.db",
    )


@pytest.mark.asyncio
async def test_dast_worker_syncs_materials_and_returns_engine_result(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers.get("X-API-Key") == "engine-key" or request.url.path == "/health"
        if request.url.path.endswith("/config"):
            config = json.loads(request.content)
            assert config["principals"]["admin_user"]["token"] == "real-token"
            return httpx.Response(200, json={"project_id": "project-1"})
        if request.url.path.endswith("/collection"):
            assert b'filename="collection.json"' in request.content
            return httpx.Response(200, json={"project_id": "project-1"})
        if request.url.path.endswith("/scan"):
            return httpx.Response(
                202,
                json={
                    "scan_id": "scan-1",
                    "status": "Running",
                    "poll_url": "/v1/scans/scan-1",
                    "started_at": "2026-08-13T00:00:00Z",
                },
            )
        if request.url.path == "/v1/scans/scan-1":
            return httpx.Response(
                200,
                json={
                    "scan_id": "scan-1",
                    "status": "Fail",
                    "exit_code": 1,
                    "results": [{"vulnerable": True}],
                    "errors": [],
                },
            )
        return httpx.Response(404)

    settings = _settings(tmp_path)
    outbox = ResultOutbox(settings.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scanner = DastScannerClient(
            settings,
            client,
            FakeRadarClient(),  # type: ignore[arg-type]
            outbox,
        )
        result = await scanner.run_scan(
            ScannerJob(
                id="job-1",
                project_id="project-1",
                agent_id=settings.id,
                engine_type="dast",
                testcase_id="TC_ATHN_1",
                request=json.dumps(
                    {
                        "ref": {
                            "project_id": "project-1",
                            "testcase_master_id": "testcase-1",
                            "exec_ids": ["exec-1"],
                        },
                        "vulnerability": "TC_ATHN_1",
                        "target": {"method": "GET", "path": "/api/v1/me"},
                        "steps": [
                            {
                                "method": "GET",
                                "path": "/api/v1/me",
                                "verify": True,
                                "expected": [{"type": "status_code", "value": 200}],
                            }
                        ],
                    }
                ),
                status="Claimed",
            ),
            "lease-token",
            asyncio.Event(),
        )

    assert result.result == "fail"
    assert result.output["scan_id"] == "scan-1"
    assert outbox.get_checkpoint("job-1") == ("project-1", "scan-1")
    assert ("POST", "/v1/projects/project-1/config") in calls
    assert ("POST", "/v1/projects/project-1/collection") in calls
    outbox.close()


@pytest.mark.asyncio
async def test_dast_heartbeat_advertises_engine_catalog(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok", "running_scans": 0, "max_concurrent_scans": 4},
            )
        return httpx.Response(
            200,
            json={"items": [{"id": "TC_ATHN_1"}, {"id": "TC_SQLI"}]},
        )

    settings = _settings(tmp_path)
    outbox = ResultOutbox(settings.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scanner = DastScannerClient(
            settings,
            client,
            FakeRadarClient(),  # type: ignore[arg-type]
            outbox,
        )
        heartbeat = await scanner.heartbeat_payload(hostname="WINDOWS-LAB", version="0.8.0")

    assert heartbeat["engine_type"] == "dast"
    assert heartbeat["device_status"] == "not_required"
    assert heartbeat["capabilities"] == ["TC_ATHN_1", "TC_SQLI"]
    assert all(item["device_type"] == "none" for item in heartbeat["capability_statuses"])
    outbox.close()
