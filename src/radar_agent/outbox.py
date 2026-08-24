import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from radar_agent.environment_profiles import normalize_radar_origin
from radar_agent.models import JobResult, PendingResult


class ResultOutbox:
    def __init__(
        self,
        database_path: Path,
        *,
        radar_origin: str | None = None,
        environment: str | None = None,
    ):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        if radar_origin:
            self._bind_profile(normalize_radar_origin(radar_origin), environment or "")
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

    def _bind_profile(self, radar_origin: str, environment: str) -> None:
        row = self._connection.execute(
            "SELECT value FROM profile_metadata WHERE key = 'radar_origin'"
        ).fetchone()
        if row and row[0] != radar_origin:
            self._connection.close()
            raise ValueError(
                "SQLite outbox belongs to a different RADAR environment "
                f"({row[0]} instead of {radar_origin})"
            )
        if row is None and environment != "development" and self._has_legacy_pending_items():
            self._connection.close()
            raise ValueError(
                "Legacy SQLite outbox contains pending DEV data. Start the Agent with "
                "the Development profile and deliver it before switching environments."
            )
        self._connection.execute(
            "INSERT OR IGNORE INTO profile_metadata (key, value) VALUES (?, ?)",
            ("radar_origin", radar_origin),
        )
        if environment:
            self._connection.execute(
                "INSERT OR IGNORE INTO profile_metadata (key, value) VALUES (?, ?)",
                ("environment", environment),
            )

    def _has_legacy_pending_items(self) -> bool:
        tables = {
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in ("pending_result", "scan_checkpoint"):
            if table in tables:
                row = self._connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                if row:
                    return True
        return False

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


def pending_outbox_items(database_path: Path) -> int:
    if not database_path.is_file():
        return 0
    try:
        database_uri = quote(database_path.resolve().as_posix(), safe="/:")
        connection = sqlite3.connect(f"file:{database_uri}?mode=ro", uri=True)
        try:
            count = 0
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in ("pending_result", "scan_checkpoint"):
                if table in tables:
                    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    count += int(row[0])
            return count
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"Could not inspect the current environment outbox: {exc}") from exc
