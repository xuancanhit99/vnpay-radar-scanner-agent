from pathlib import Path

import pytest

from radar_agent.job_runner import JobRunner
from radar_agent.models import JobClaim, JobResult, ScannerJob
from radar_agent.outbox import ResultOutbox
from radar_agent.settings import AgentSettings


class FakeRadarClient:
    def __init__(self):
        self.started: list[str] = []
        self.results: list[tuple[str, JobResult]] = []

    async def start_job(self, job_id: str, lease_token: str) -> None:
        self.started.append(job_id)

    async def renew_lease(self, job_id: str, lease_token: str) -> bool:
        return False

    async def submit_result(self, job_id: str, lease_token: str, result: JobResult) -> None:
        self.results.append((job_id, result))


class FakeScannerClient:
    async def run_scan(self, job: ScannerJob) -> JobResult:
        return JobResult(result="pass", detail="No DEBUGGABLE flag", output={"ok": True})


@pytest.mark.asyncio
async def test_job_runner_stores_then_delivers_result(tmp_path: Path) -> None:
    settings = AgentSettings(
        client_secret="secret",
        database_path=tmp_path / "agent.db",
        lease_renew_interval_seconds=5,
    )
    radar = FakeRadarClient()
    outbox = ResultOutbox(settings.database_path)
    runner = JobRunner(settings, radar, FakeScannerClient(), outbox)  # type: ignore[arg-type]
    claim = JobClaim(
        job=ScannerJob(
            id="job-1",
            agent_id=settings.id,
            package_name="com.vnpay.bidv",
            testcase_id="TC-MOBI-3",
            status="claimed",
        ),
        lease_token="lease-token",
        lease_seconds=45,
    )

    await runner.run(claim)

    assert radar.started == ["job-1"]
    assert radar.results[0][0] == "job-1"
    assert radar.results[0][1].result == "pass"
    assert outbox.list_pending() == []
    outbox.close()
