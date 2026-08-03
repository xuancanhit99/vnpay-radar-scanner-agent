from typing import Any, Literal

from pydantic import BaseModel


class ScannerJob(BaseModel):
    id: str
    agent_id: str
    package_name: str
    testcase_id: str
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
