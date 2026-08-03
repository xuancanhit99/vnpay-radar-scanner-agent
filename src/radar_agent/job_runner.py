import asyncio
import logging

from radar_agent.models import JobClaim
from radar_agent.outbox import ResultOutbox
from radar_agent.radar_client import RadarClient
from radar_agent.scanner_client import ScannerClient
from radar_agent.settings import AgentSettings

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        settings: AgentSettings,
        radar: RadarClient,
        scanner: ScannerClient,
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
        renewal_task = asyncio.create_task(
            self._renew_lease(job.id, claim.lease_token, stop_renewal)
        )
        try:
            result = await self._scanner.run_scan(job)
            self._outbox.put(job.id, claim.lease_token, result)
        finally:
            stop_renewal.set()
            await renewal_task
        await self.flush_outbox()

    async def _renew_lease(
        self,
        job_id: str,
        lease_token: str,
        stop: asyncio.Event,
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
                    cancel_requested = await self._radar.renew_lease(job_id, lease_token)
                    if cancel_requested:
                        logger.warning("Job cancellation requested", extra={"job_id": job_id})
                except Exception:
                    logger.exception("Could not renew scanner job lease", extra={"job_id": job_id})
