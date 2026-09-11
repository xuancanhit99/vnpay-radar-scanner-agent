import asyncio
import json
import time
from typing import Any
from urllib.parse import quote

import httpx

from radar_agent.models import JobResult, ScannerJob
from radar_agent.outbox import ResultOutbox
from radar_agent.radar_client import RadarClient
from radar_agent.settings import AgentSettings


class DastScannerClient:
    def __init__(
        self,
        settings: AgentSettings,
        client: httpx.AsyncClient,
        radar: RadarClient,
        outbox: ResultOutbox,
    ):
        self._settings = settings
        self._client = client
        self._radar = radar
        self._outbox = outbox
        self._api_key = settings.resolved_dast_engine_api_key()
        self._capabilities: list[str] = []
        self._scan_in_progress = False

    @property
    def _base_url(self) -> str:
        return self._settings.dast_engine_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    async def heartbeat_payload(self, *, hostname: str, version: str) -> dict[str, Any]:
        scanner_status = "unavailable"
        try:
            health = await self._client.get(f"{self._base_url}/health", timeout=5)
            health.raise_for_status()
            payload = health.json()
            at_capacity = int(payload.get("running_scans") or 0) >= int(
                payload.get("max_concurrent_scans") or 1
            )
            scanner_status = "busy" if self._scan_in_progress or at_capacity else "ready"

            catalog = await self._client.get(
                f"{self._base_url}/v1/vulnerabilities",
                headers=self._headers,
                timeout=10,
            )
            catalog.raise_for_status()
            self._capabilities = [
                str(item["id"])
                for item in catalog.json().get("items", [])
                if isinstance(item, dict) and item.get("id")
            ]
        except (httpx.HTTPError, TypeError, ValueError):
            scanner_status = "unavailable"

        ready = scanner_status == "ready"
        return {
            "agent_id": self._settings.id,
            "display_name": self._settings.display_name,
            "hostname": hostname,
            "version": version,
            "engine_type": "dast",
            "scanner_status": scanner_status,
            "device_status": "not_required",
            "device_serial": None,
            "device_model": None,
            "capabilities": self._capabilities,
            "capability_statuses": [
                {
                    "testcase_id": testcase_id,
                    "name": testcase_id,
                    "device_type": "none",
                    "timeout_seconds": self._settings.dast_timeout_seconds,
                    "ready": ready,
                    "reason": None if ready else "DAST engine is unavailable or busy",
                }
                for testcase_id in self._capabilities
            ],
        }

    async def run_scan(
        self,
        job: ScannerJob,
        lease_token: str,
        cancel_requested: asyncio.Event,
    ) -> JobResult:
        self._scan_in_progress = True
        try:
            if job.job_type == "config_sync":
                return await self._sync_config(job, lease_token)
            if job.job_type == "collection_sync":
                return await self._sync_collection(job, lease_token)
            if job.job_type == "scan":
                return await self._run_scenario(job, cancel_requested)
            return await self._run_legacy_scan(job, lease_token, cancel_requested)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            return JobResult(
                result="error",
                detail=f"DAST engine execution failed: {exc}",
                output={"error_type": type(exc).__name__},
            )
        finally:
            self._scan_in_progress = False

    def _project_id(self, job: ScannerJob) -> str:
        if not job.project_id:
            raise ValueError("DAST job is missing project_id")
        return quote(job.project_id, safe="")

    async def _sync_config(self, job: ScannerJob, lease_token: str) -> JobResult:
        project_id = self._project_id(job)
        config = await self._radar.get_dast_config(job.id, lease_token)
        config["principals"] = self._validated_principals(config)
        response = await self._client.post(
            f"{self._base_url}/v1/projects/{project_id}/config",
            headers=self._headers,
            json=config,
            timeout=30,
        )
        response.raise_for_status()
        return JobResult(
            result="pass",
            detail="DAST project config synchronized",
            output={"resource": "config", "updated": True},
        )

    async def _sync_collection(self, job: ScannerJob, lease_token: str) -> JobResult:
        project_id = self._project_id(job)
        material = await self._radar.get_dast_collection(job.id, lease_token)
        if material.get("empty") is True:
            return JobResult(
                result="pass",
                detail="RADAR project has no APIs; engine collection retained",
                output={
                    "resource": "collection",
                    "updated": False,
                    "empty": True,
                    "engine_collection_retained": True,
                },
            )
        collection = material.get("collection")
        if not isinstance(collection, dict):
            raise ValueError("RADAR returned an invalid DAST collection material")
        response = await self._post_collection(project_id, collection)
        response.raise_for_status()
        return JobResult(
            result="pass",
            detail="DAST project collection synchronized",
            output={"resource": "collection", "updated": True, "empty": False},
        )

    async def _post_collection(
        self, project_id: str, collection: dict[str, Any]
    ) -> httpx.Response:
        return await self._client.post(
            f"{self._base_url}/v1/projects/{project_id}/collection",
            headers=self._headers,
            files={
                "file": (
                    "collection.json",
                    json.dumps(collection, ensure_ascii=False).encode("utf-8"),
                    "application/json",
                )
            },
            timeout=120,
        )

    async def _run_scenario(
        self,
        job: ScannerJob,
        cancel_requested: asyncio.Event,
    ) -> JobResult:
        project_id = self._project_id(job)
        if not job.request:
            raise ValueError("DAST scan job is missing request payload")
        request_payload = json.loads(job.request)
        return await self._start_or_resume_scan(
            job, project_id, request_payload, cancel_requested
        )

    async def _run_legacy_scan(
        self,
        job: ScannerJob,
        lease_token: str,
        cancel_requested: asyncio.Event,
    ) -> JobResult:
        project_id = self._project_id(job)
        if not job.request:
            raise ValueError("Legacy DAST job is missing request payload")
        request_payload = json.loads(job.request)
        config = await self._radar.get_dast_config(job.id, lease_token)
        collection = await self._radar.get_dast_collection(job.id, lease_token)
        config["principals"] = self._validated_principals(config)
        config_response = await self._client.post(
            f"{self._base_url}/v1/projects/{project_id}/config",
            headers=self._headers,
            json=config,
            timeout=30,
        )
        config_response.raise_for_status()
        collection_response = await self._post_collection(project_id, collection)
        collection_response.raise_for_status()
        return await self._start_or_resume_scan(
            job, project_id, request_payload, cancel_requested
        )

    async def _start_or_resume_scan(
        self,
        job: ScannerJob,
        project_id: str,
        request_payload: dict[str, Any],
        cancel_requested: asyncio.Event,
    ) -> JobResult:
        checkpoint = self._outbox.get_checkpoint(job.id)
        if checkpoint is not None:
            checkpoint_project, engine_scan_id = checkpoint
            if checkpoint_project == job.project_id:
                resumed = await self._poll_scan(
                    engine_scan_id,
                    cancel_requested,
                    allow_missing=True,
                )
                if resumed is not None:
                    return self._to_job_result(resumed)
            self._outbox.delete_checkpoint(job.id)

        start_response = await self._client.post(
            f"{self._base_url}/v1/projects/{project_id}/scan",
            headers=self._headers,
            params={"wait": 0},
            json=request_payload,
            timeout=30,
        )
        start_response.raise_for_status()
        started = start_response.json()
        if str(started.get("status")) != "Running":
            return self._to_job_result(started)

        engine_scan_id = str(started["scan_id"])
        self._outbox.put_checkpoint(job.id, job.project_id or "", engine_scan_id)
        completed = await self._poll_scan(engine_scan_id, cancel_requested)
        if completed is None:
            raise RuntimeError("DAST scan checkpoint disappeared from the engine")
        return self._to_job_result(completed)

    def _validated_principals(self, config: dict[str, Any]) -> dict[str, dict]:
        declared = config.get("principals")
        if not isinstance(declared, dict) or not declared:
            raise ValueError("Project DAST config has no declared principals")
        if not all(isinstance(value, dict) and value for value in declared.values()):
            raise ValueError("RADAR returned an empty DAST principal credential")
        serialized = json.dumps(declared)
        if "<PASTE_TOKEN_HERE>" in serialized:
            raise ValueError("RADAR returned a DAST principal token placeholder")
        return declared

    async def _poll_scan(
        self,
        scan_id: str,
        cancel_requested: asyncio.Event,
        *,
        allow_missing: bool = False,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + self._settings.dast_timeout_seconds
        path = f"{self._base_url}/v1/scans/{quote(scan_id, safe='')}"
        while time.monotonic() < deadline:
            if cancel_requested.is_set():
                response = await self._client.delete(path, headers=self._headers, timeout=30)
                if response.status_code != 404:
                    response.raise_for_status()
                    return dict(response.json())
                return None
            response = await self._client.get(path, headers=self._headers, timeout=30)
            if response.status_code == 404 and allow_missing:
                return None
            response.raise_for_status()
            payload = dict(response.json())
            if str(payload.get("status")) != "Running":
                return payload
            await asyncio.sleep(self._settings.dast_poll_interval_seconds)
        raise RuntimeError(
            f"DAST scan exceeded {self._settings.dast_timeout_seconds} seconds"
        )

    @staticmethod
    def _to_job_result(payload: dict[str, Any]) -> JobResult:
        status = str(payload.get("status") or "Error")
        result = {
            "Pass": "pass",
            "Fail": "fail",
            "N/A": "warning",
            "Cancelled": "warning",
            "Error": "error",
        }.get(status, "error")
        result_count = len(payload.get("results") or [])
        error_count = len(payload.get("errors") or [])
        detail = f"DAST {status}: {result_count} result(s), {error_count} error(s)"
        return JobResult(result=result, detail=detail, output=payload)
