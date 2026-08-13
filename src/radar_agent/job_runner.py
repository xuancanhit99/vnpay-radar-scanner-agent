import asyncio
import logging
from typing import Protocol

from radar_agent.models import JobClaim, JobResult, ScannerJob
from radar_agent.outbox import ResultOutbox
from radar_agent.radar_client import RadarClient
from radar_agent.settings import AgentSettings

logger = logging.getLogger(__name__)


class ScanEngineClient(Protocol):
    async def run_scan(
        self,
        job: ScannerJob,
        lease_token: str,
        cancel_requested: asyncio.Event,
    ) -> JobResult: ...


class JobRunner:
    def __init__(
        self,
        settings: AgentSettings,
        radar: RadarClient,
        scanner: ScanEngineClient,
        outbox: ResultOutbox,
    ):
        self._settings = settings
        self._radar = radar
        self._scanner = scanner
        self._outbox = outbox

    async def flush_outbox(self) -> None:
        for pending in self._outbox.list_pending():
            await self._radar.submit_result(
                pending.job_id,
                pending.lease_token,
                pending.result,
            )
            self._outbox.delete(pending.job_id)
            logger.info("Delivered scanner result", extra={"job_id": pending.job_id})

    async def run(self, claim: JobClaim) -> None:
        job = claim.job
        await self._radar.start_job(job.id, claim.lease_token)
        stop_renewal = asyncio.Event()
        cancel_requested = asyncio.Event()
        renewal_task = asyncio.create_task(
            self._renew_lease(
                job.id,
                claim.lease_token,
                stop_renewal,
                cancel_requested,
            )
        )
        try:
            result = await self._scanner.run_scan(
                job,
                claim.lease_token,
                cancel_requested,
            )
            self._outbox.put(job.id, claim.lease_token, result)
            self._outbox.delete_checkpoint(job.id)
        finally:
            stop_renewal.set()
            await renewal_task
        await self.flush_outbox()

    async def _renew_lease(
        self,
        job_id: str,
        lease_token: str,
        stop: asyncio.Event,
        cancel_requested: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self._settings.lease_renew_interval_seconds,
                )
                return
            except TimeoutError:
                try:
                    should_cancel = await self._radar.renew_lease(job_id, lease_token)
                    if should_cancel:
                        cancel_requested.set()
                        logger.warning("Job cancellation requested", extra={"job_id": job_id})
                except Exception:
                    logger.exception("Could not renew scanner job lease", extra={"job_id": job_id})
