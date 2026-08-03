import asyncio
import ssl

import pytest

from radar_agent.service import _heartbeat_loop, _tls_verifier
from radar_agent.settings import AgentSettings


def test_tls_verifier_uses_system_trust_store() -> None:
    assert isinstance(_tls_verifier(True), ssl.SSLContext)


def test_tls_verifier_can_be_disabled_explicitly() -> None:
    assert _tls_verifier(False) is False


class FakeScannerClient:
    def __init__(self) -> None:
        self.calls = 0

    async def heartbeat_payload(self, *, hostname: str, version: str) -> dict:
        self.calls += 1
        return {"hostname": hostname, "version": version}


class FakeRadarClient:
    def __init__(self, stop: asyncio.Event, *, fail_first: bool = False) -> None:
        self.stop = stop
        self.fail_first = fail_first
        self.calls = 0

    async def heartbeat(self, payload: dict) -> None:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("temporary heartbeat failure")
        self.stop.set()


@pytest.mark.asyncio
async def test_heartbeat_loop_sets_ready_after_backend_accepts_heartbeat() -> None:
    settings = AgentSettings(_env_file=None, client_secret="test-secret")
    ready = asyncio.Event()
    stop = asyncio.Event()
    scanner = FakeScannerClient()
    radar = FakeRadarClient(stop)

    await _heartbeat_loop(
        settings,
        radar,  # type: ignore[arg-type]
        scanner,  # type: ignore[arg-type]
        hostname="WINDOWS-LAB",
        ready=ready,
        stop=stop,
    )

    assert ready.is_set()
    assert radar.calls == 1
    assert scanner.calls == 1


@pytest.mark.asyncio
async def test_heartbeat_loop_retries_without_stopping_worker() -> None:
    settings = AgentSettings(_env_file=None, client_secret="test-secret")
    settings.heartbeat_interval_seconds = 0
    ready = asyncio.Event()
    stop = asyncio.Event()
    scanner = FakeScannerClient()
    radar = FakeRadarClient(stop, fail_first=True)

    await asyncio.wait_for(
        _heartbeat_loop(
            settings,
            radar,  # type: ignore[arg-type]
            scanner,  # type: ignore[arg-type]
            hostname="WINDOWS-LAB",
            ready=ready,
            stop=stop,
        ),
        timeout=1,
    )

    assert ready.is_set()
    assert radar.calls == 2
    assert scanner.calls == 2
