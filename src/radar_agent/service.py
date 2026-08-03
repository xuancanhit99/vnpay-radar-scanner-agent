import asyncio
import logging
import socket
import ssl
from contextlib import suppress

import httpx

from radar_agent import __version__
from radar_agent.job_runner import JobRunner
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
    scanner: ScannerClient,
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
    outbox = ResultOutbox(settings.database_path)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        verify=_tls_verifier(settings.verify_tls),
        timeout=timeout,
    ) as client:
        token_provider = TokenProvider(settings, client)
        radar = RadarClient(settings, client, token_provider)
        scanner = ScannerClient(settings, client)
        runner = JobRunner(settings, radar, scanner, outbox)
        hostname = socket.gethostname()
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
            name="scanner-agent-heartbeat",
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
                    logger.exception("Scanner agent loop failed")
                    await asyncio.sleep(settings.retry_delay_seconds)
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            outbox.close()
