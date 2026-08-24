from pathlib import Path

import pytest

from radar_agent.models import JobResult
from radar_agent.outbox import ResultOutbox, pending_outbox_items


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


def test_outbox_is_bound_to_one_radar_origin(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    outbox = ResultOutbox(
        database,
        radar_origin="https://radar.vnpay.dev",
        environment="development",
    )
    outbox.close()

    reopened = ResultOutbox(
        database,
        radar_origin="https://radar.vnpay.dev/",
        environment="development",
    )
    reopened.close()

    with pytest.raises(ValueError, match="different RADAR environment"):
        ResultOutbox(
            database,
            radar_origin="https://radar.vnpaytest.vn",
            environment="uat",
        )


def test_legacy_pending_dev_data_cannot_be_adopted_by_uat(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    legacy_outbox = ResultOutbox(database)
    legacy_outbox.put(
        "job-legacy",
        "lease-token",
        JobResult(result="pass", detail="done", output={}),
    )
    legacy_outbox.close()

    with pytest.raises(ValueError, match="pending DEV data"):
        ResultOutbox(
            database,
            radar_origin="https://radar.vnpaytest.vn",
            environment="uat",
        )


def test_pending_outbox_items_counts_results_and_checkpoints(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    outbox = ResultOutbox(database)
    outbox.put(
        "job-result",
        "lease-token",
        JobResult(result="pass", detail="done", output={}),
    )
    outbox.put_checkpoint("job-checkpoint", "project-1", "scan-1")
    outbox.close()

    assert pending_outbox_items(database) == 2


def test_pending_outbox_items_rejects_a_corrupt_database(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    database.write_bytes(b"not a sqlite database")

    with pytest.raises(ValueError, match="Could not inspect"):
        pending_outbox_items(database)
