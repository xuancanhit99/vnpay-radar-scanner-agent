import json
import sqlite3
from pathlib import Path

from radar_agent.models import JobResult, PendingResult


class ResultOutbox:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_result (
                job_id TEXT PRIMARY KEY,
                lease_token TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_checkpoint (
                job_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                engine_scan_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.commit()

    def put(self, job_id: str, lease_token: str, result: JobResult) -> None:
        self._connection.execute(
            """
            INSERT INTO pending_result (job_id, lease_token, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                lease_token = excluded.lease_token,
                payload = excluded.payload
            """,
            (job_id, lease_token, result.model_dump_json()),
        )
        self._connection.commit()

    def list_pending(self) -> list[PendingResult]:
        rows = self._connection.execute(
            "SELECT job_id, lease_token, payload FROM pending_result ORDER BY created_at"
        ).fetchall()
        return [
            PendingResult(
                job_id=row[0],
                lease_token=row[1],
                result=JobResult.model_validate(json.loads(row[2])),
            )
            for row in rows
        ]

    def delete(self, job_id: str) -> None:
        self._connection.execute("DELETE FROM pending_result WHERE job_id = ?", (job_id,))
        self._connection.commit()

    def put_checkpoint(self, job_id: str, project_id: str, engine_scan_id: str) -> None:
        self._connection.execute(
            """
            INSERT INTO scan_checkpoint (job_id, project_id, engine_scan_id)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                project_id = excluded.project_id,
                engine_scan_id = excluded.engine_scan_id
            """,
            (job_id, project_id, engine_scan_id),
        )
        self._connection.commit()

    def get_checkpoint(self, job_id: str) -> tuple[str, str] | None:
        row = self._connection.execute(
            "SELECT project_id, engine_scan_id FROM scan_checkpoint WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return (str(row[0]), str(row[1])) if row else None

    def delete_checkpoint(self, job_id: str) -> None:
        self._connection.execute("DELETE FROM scan_checkpoint WHERE job_id = ?", (job_id,))
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
