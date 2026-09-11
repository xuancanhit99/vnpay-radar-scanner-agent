from typing import Any, Literal

from pydantic import BaseModel


class ScannerJob(BaseModel):
    id: str
    project_id: str | None = None
    agent_id: str | None = None
    engine_type: Literal["apk", "dast"] = "apk"
    job_type: Literal["scan", "config_sync", "collection_sync"] | None = None
    package_name: str | None = None
    testcase_id: str | None = None
    request: str | None = None
    status: str


class JobClaim(BaseModel):
    job: ScannerJob
    lease_token: str
    lease_seconds: int


class JobResult(BaseModel):
    result: Literal["pass", "fail", "warning", "error"]
    detail: str
    output: dict[str, Any]


class PendingResult(BaseModel):
    job_id: str
    lease_token: str
    result: JobResult
