import httpx
import pytest

from radar_agent.radar_client import RadarClient
from radar_agent.settings import AgentSettings


class FakeTokenProvider:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return "access-token"


@pytest.mark.asyncio
async def test_claim_job_treats_incompatible_queue_as_no_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr("radar_agent.radar_client.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(409, json={"detail": "No compatible queued job"})

    settings = AgentSettings(
        id="windows-lab-01-dast",
        poll_wait_seconds=0,
        retry_delay_seconds=7,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        radar = RadarClient(settings, client, FakeTokenProvider())  # type: ignore[arg-type]
        assert await radar.claim_job() is None
    assert sleep_delays == [7]


@pytest.mark.asyncio
async def test_claim_job_keeps_unexpected_http_errors_visible() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "backend unavailable"})

    settings = AgentSettings(id="windows-lab-01-dast", poll_wait_seconds=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        radar = RadarClient(settings, client, FakeTokenProvider())  # type: ignore[arg-type]
        with pytest.raises(httpx.HTTPStatusError):
            await radar.claim_job()
