import subprocess

from radar_agent import service_control


def test_query_service_reads_windows_service_state(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"State":"Running","StartMode":"Auto"}',
        stderr="",
    )
    monkeypatch.setattr(service_control.os, "name", "nt")
    monkeypatch.setattr(service_control, "_run", lambda _command: result)

    state = service_control.query_service()

    assert state.installed is True
    assert state.status == "running"
    assert state.start_mode == "Auto"


def test_query_service_reports_missing_service(monkeypatch) -> None:
    result = subprocess.CompletedProcess(args=[], returncode=3, stdout="", stderr="")
    monkeypatch.setattr(service_control.os, "name", "nt")
    monkeypatch.setattr(service_control, "_run", lambda _command: result)

    state = service_control.query_service()

    assert state.installed is False
    assert state.status == "not-installed"
