from typing import Any

import httpx

from radar_agent.models import JobClaim, JobResult
from radar_agent.settings import AgentSettings
from radar_agent.token_provider import TokenProvider


class RadarClient:
    def __init__(
        self,
        settings: AgentSettings,
        client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ):
        self._settings = settings
        self._client = client
        self._token_provider = token_provider

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            token = await self._token_provider.get_token(force_refresh=attempt == 1)
            response = await self._client.request(
                method,
                f"{self._settings.base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
            if response.status_code != 401 or attempt == 1:
                response.raise_for_status()
                return response
        raise RuntimeError("Unreachable token retry state")

    async def heartbeat(self, payload: dict[str, Any]) -> None:
        await self._request("POST", "/internal/scanner/agents/heartbeat", json=payload)

    async def claim_job(self) -> JobClaim | None:
        response = await self._request(
            "POST",
            f"/internal/scanner/jobs/claim?wait_seconds={self._settings.poll_wait_seconds}",
            json={"agent_id": self._settings.id},
            timeout=self._settings.poll_wait_seconds + 15,
        )
        payload = response.json()
        return JobClaim.model_validate(payload) if payload else None

    async def start_job(self, job_id: str, lease_token: str) -> None:
        await self._request(
            "POST",
            f"/internal/scanner/jobs/{job_id}/start",
            json={"lease_token": lease_token},
        )

    async def renew_lease(self, job_id: str, lease_token: str) -> bool:
        response = await self._request(
            "POST",
            f"/internal/scanner/jobs/{job_id}/lease",
            json={"lease_token": lease_token},
        )
        return bool(response.json().get("cancel_requested"))

    async def submit_result(self, job_id: str, lease_token: str, result: JobResult) -> None:
        await self._request(
            "POST",
            f"/internal/scanner/jobs/{job_id}/result",
            json={"lease_token": lease_token, **result.model_dump()},
        )
