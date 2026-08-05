from radar_agent import updater
from radar_agent.update_service import InstallerStatus
from radar_agent.updater import UPDATE_STEPS, ProgressState, progress_state, start_installer


def test_progress_starts_after_package_is_ready() -> None:
    assert progress_state(None, "0.5.8") == ProgressState(completed=1, active=1)


def test_progress_maps_installer_stage_to_real_milestone() -> None:
    status = InstallerStatus(
        state="installing",
        version="0.5.8",
        message="",
        stage="installing_files",
    )

    assert progress_state(status, "0.5.8") == ProgressState(completed=3, active=3)


def test_progress_marks_failed_installer_stage() -> None:
    status = InstallerStatus(
        state="failed",
        version="0.5.8",
        message="Service failed to start.",
        stage="starting_service",
    )

    assert progress_state(status, "0.5.8") == ProgressState(
        completed=4,
        active=None,
        failed=4,
    )


def test_progress_completes_all_steps_after_success() -> None:
    status = InstallerStatus(
        state="success",
        version="0.5.8",
        message="Installation completed successfully.",
        stage="completed",
    )

    assert progress_state(status, "0.5.8") == ProgressState(
        completed=len(UPDATE_STEPS),
        active=None,
    )


def test_updater_starts_installer_with_recursion_guard(tmp_path, monkeypatch) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    calls = []

    def fake_popen(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return object()

    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    start_installer(installer)

    assert calls == [
        (
            [str(installer), "/S", "/UPDATER_CHILD"],
            {"cwd": str(tmp_path), "close_fds": True},
        )
    ]
