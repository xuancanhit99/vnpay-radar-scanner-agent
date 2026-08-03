from pathlib import Path

from radar_agent.models import JobResult
from radar_agent.outbox import ResultOutbox


def test_outbox_persists_result_until_deleted(tmp_path: Path) -> None:
    outbox = ResultOutbox(tmp_path / "agent.db")
    result = JobResult(result="pass", detail="No DEBUGGABLE flag", output={"flag": False})

    outbox.put("job-1", "lease-token", result)
    pending = outbox.list_pending()

    assert len(pending) == 1
    assert pending[0].job_id == "job-1"
    assert pending[0].result.result == "pass"

    outbox.delete("job-1")
    assert outbox.list_pending() == []
    outbox.close()
