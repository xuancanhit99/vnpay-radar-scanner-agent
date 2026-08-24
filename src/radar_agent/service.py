import asyncio
import logging
import socket
import ssl
from contextlib import suppress

import httpx

from radar_agent import __version__
from radar_agent.dast_client import DastScannerClient
from radar_agent.job_runner import JobRunner, ScanEngineClient
from radar_agent.outbox import ResultOutbox
from radar_agent.radar_client import RadarClient
from radar_agent.scanner_client import ScannerClient
from radar_agent.settings import AgentSettings
from radar_agent.token_provider import TokenProvider

logger = logging.getLogger(__name__)


def _tls_verifier(verify_tls: bool) -> ssl.SSLContext | bool:
    return ssl.create_default_context() if verify_tls else False


async def _heartbeat_loop(
    settings: AgentSettings,
    radar: RadarClient,
    scanner: ScanEngineClient,
    *,
    hostname: str,
    ready: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            heartbeat = await scanner.heartbeat_payload(
                hostname=hostname,
                version=__version__,
            )
            await radar.heartbeat(heartbeat)
            ready.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not send scanner agent heartbeat")

        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.heartbeat_interval_seconds,
            )
        except TimeoutError:
            continue


async def run_agent(settings: AgentSettings) -> None:
    settings.validate_runtime()
    outbox = ResultOutbox(
        settings.database_path,
        radar_origin=settings.radar_origin,
        environment=settings.environment,
    )
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        verify=_tls_verifier(settings.verify_tls),
        timeout=timeout,
    ) as client:
        token_provider = TokenProvider(settings, client)
        hostname = socket.gethostname()
        apk_radar = RadarClient(settings, client, token_provider)
        workers = [
            asyncio.create_task(
                _worker_loop(
                    settings,
                    apk_radar,
                    ScannerClient(settings, client),
                    outbox,
                    hostname=hostname,
                ),
                name="scanner-agent-apk",
            )
        ]
        if settings.dast_enabled:
            dast_settings = settings.model_copy(
                update={
                    "id": settings.resolved_dast_agent_id,
                    "display_name": settings.resolved_dast_display_name,
                }
            )
            dast_radar = RadarClient(dast_settings, client, token_provider)
            workers.append(
                asyncio.create_task(
                    _worker_loop(
                        dast_settings,
                        dast_radar,
                        DastScannerClient(dast_settings, client, dast_radar, outbox),
                        outbox,
                        hostname=hostname,
                    ),
                    name="scanner-agent-dast",
                )
            )
        try:
            await asyncio.gather(*workers)
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            outbox.close()


async def _worker_loop(
    settings: AgentSettings,
    radar: RadarClient,
    scanner: ScanEngineClient,
    outbox: ResultOutbox,
    *,
    hostname: str,
) -> None:
    runner = JobRunner(settings, radar, scanner, outbox)
    logger.info("Scanner agent started", extra={"agent_id": settings.id, "hostname": hostname})
    heartbeat_ready = asyncio.Event()
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            settings,
            radar,
            scanner,
            hostname=hostname,
            ready=heartbeat_ready,
            stop=heartbeat_stop,
        ),
        name=f"{settings.id}-heartbeat",
    )
    try:
        await heartbeat_ready.wait()
        while True:
            try:
                await runner.flush_outbox()
                claim = await radar.claim_job()
                if claim is not None:
                    logger.info(
                        "Claimed scanner job",
                        extra={"job_id": claim.job.id, "testcase_id": claim.job.testcase_id},
                    )
                    await runner.run(claim)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scanner agent loop failed", extra={"agent_id": settings.id})
                await asyncio.sleep(settings.retry_delay_seconds)
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
