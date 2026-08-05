import hashlib
import sys
from contextlib import nullcontext

import httpx
import pytest

from radar_agent import update_service
from radar_agent.manager import ManagerWindow
from radar_agent.update_service import (
    InstallerStatus,
    UpdateError,
    check_for_update,
    download_installer,
    launch_installer,
    launch_updater,
    read_installer_status,
)


class _StringValue:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _StatusLabel:
    def __init__(self) -> None:
        self.style = ""

    def configure(self, *, style: str) -> None:
        self.style = style


def _release_payload(version: str, installer: bytes) -> dict:
    installer_name = f"VNPAYRadarScannerAgent-Setup-{version}-x64.exe"
    checksum_name = f"VNPAYRadarScannerAgent-{version}-SHA256SUMS.txt"
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/example/releases/tag/v{version}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": installer_name,
                "browser_download_url": f"https://github.com/example/{installer_name}",
            },
            {
                "name": checksum_name,
                "browser_download_url": f"https://github.com/example/{checksum_name}",
            },
        ],
        "checksum": f"{hashlib.sha256(installer).hexdigest()}  {installer_name}\n",
    }


def _client_for_release(payload: dict, installer: bytes) -> httpx.Client:
    def sync_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=payload)
        if request.url.path.endswith("SHA256SUMS.txt"):
            return httpx.Response(200, text=payload["checksum"])
        if request.url.path.endswith(".exe"):
            return httpx.Response(
                200,
                content=installer,
                headers={"Content-Length": str(len(installer))},
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(sync_handler), follow_redirects=True)


def test_check_for_update_returns_verified_release() -> None:
    installer = b"signed-installer-content"
    payload = _release_payload("0.4.0", installer)
    with _client_for_release(payload, installer) as client:
        update = check_for_update("0.3.2", client=client)

    assert update.available is True
    assert update.latest_version == "0.4.0"
    assert update.sha256 == hashlib.sha256(installer).hexdigest()


def test_check_for_update_reports_current_version() -> None:
    installer = b"installer"
    payload = _release_payload("0.4.0", installer)
    with _client_for_release(payload, installer) as client:
        update = check_for_update("0.4.0", client=client)

    assert update.available is False


def test_check_for_update_rejects_untrusted_asset_url() -> None:
    installer = b"installer"
    payload = _release_payload("0.4.0", installer)
    payload["assets"][0]["browser_download_url"] = "https://downloads.example/agent.exe"
    with _client_for_release(payload, installer) as client:
        with pytest.raises(UpdateError, match="trusted GitHub HTTPS URL"):
            check_for_update("0.3.2", client=client)


def test_download_installer_verifies_sha256(tmp_path) -> None:
    installer = b"verified-installer-content"
    payload = _release_payload("0.4.0", installer)
    with _client_for_release(payload, installer) as client:
        update = check_for_update("0.3.2", client=client)
        path = download_installer(update, tmp_path, client=client)

    assert path.read_bytes() == installer
    assert not path.with_suffix(".exe.partial").exists()


def test_download_installer_removes_partial_file_on_checksum_mismatch(tmp_path) -> None:
    installer = b"corrupted-installer"
    payload = _release_payload("0.4.0", b"expected-installer")
    with _client_for_release(payload, installer) as client:
        update = check_for_update("0.3.2", client=client)
        with pytest.raises(UpdateError, match="SHA-256"):
            download_installer(update, tmp_path, client=client)

    destination = tmp_path / update.installer_name
    assert not destination.exists()
    assert not destination.with_suffix(".exe.partial").exists()


def test_launch_installer_requests_windows_elevation(tmp_path, monkeypatch) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")
    calls = []

    class Shell32:
        def ShellExecuteW(self, *args):
            calls.append(args)
            return 42

    monkeypatch.setattr(update_service.os, "name", "nt")
    monkeypatch.setattr(
        update_service.ctypes,
        "windll",
        type("Windll", (), {"shell32": Shell32()})(),
        raising=False,
    )

    launch_installer(installer)

    assert calls == [(None, "runas", str(installer), "/S", str(installer.parent), 1)]


def test_launch_installer_reports_windows_shell_error(tmp_path, monkeypatch) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"installer")

    class Shell32:
        def ShellExecuteW(self, *args):
            return 5

    monkeypatch.setattr(update_service.os, "name", "nt")
    monkeypatch.setattr(
        update_service.ctypes,
        "windll",
        type("Windll", (), {"shell32": Shell32()})(),
        raising=False,
    )

    with pytest.raises(UpdateError, match="Windows error 5"):
        launch_installer(installer)


def test_read_installer_status_from_windows_registry(monkeypatch) -> None:
    values = {
        "LastUpdateState": "failed",
        "LastUpdateVersion": "0.5.6",
        "LastUpdateMessage": "Service could not be restarted.",
        "LastUpdateStage": "starting_service",
    }
    fake_winreg = type(
        "FakeWinreg",
        (),
        {
            "HKEY_LOCAL_MACHINE": object(),
            "OpenKey": staticmethod(lambda *_args: nullcontext(object())),
            "QueryValueEx": staticmethod(lambda _key, name: (values[name], 1)),
        },
    )
    monkeypatch.setattr(update_service.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    status = read_installer_status()

    assert status is not None
    assert status.state == "failed"
    assert status.version == "0.5.6"
    assert status.message == "Service could not be restarted."
    assert status.stage == "starting_service"


def test_read_installer_status_supports_older_installer_without_stage(monkeypatch) -> None:
    values = {
        "LastUpdateState": "success",
        "LastUpdateVersion": "0.5.7",
        "LastUpdateMessage": "Installation completed successfully.",
    }

    def query_value(_key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    fake_winreg = type(
        "FakeWinreg",
        (),
        {
            "HKEY_LOCAL_MACHINE": object(),
            "OpenKey": staticmethod(lambda *_args: nullcontext(object())),
            "QueryValueEx": staticmethod(query_value),
        },
    )
    monkeypatch.setattr(update_service.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    status = read_installer_status()

    assert status is not None
    assert status.stage == ""


def test_launch_updater_copies_executable_next_to_downloaded_installer(
    tmp_path, monkeypatch
) -> None:
    source_directory = tmp_path / "installed"
    download_directory = tmp_path / "updates"
    source_directory.mkdir()
    download_directory.mkdir()
    updater = source_directory / "radar-scanner-updater.exe"
    updater.write_bytes(b"updater")
    installer = download_directory / "setup.exe"
    installer.write_bytes(b"installer")
    calls = []

    def fake_popen(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return object()

    monkeypatch.setattr(update_service.os, "name", "nt")
    monkeypatch.setattr(update_service.subprocess, "Popen", fake_popen)

    launched = launch_updater(updater, installer, "0.5.8")

    assert launched == download_directory / "radar-scanner-updater-0.5.8.exe"
    assert launched.read_bytes() == b"updater"
    assert calls == [
        (
            [
                str(launched),
                "--installer",
                str(installer),
                "--version",
                "0.5.8",
            ],
            {"cwd": str(download_directory), "close_fds": True},
        )
    ]


def test_launch_updater_rejects_invalid_target_version(tmp_path, monkeypatch) -> None:
    updater = tmp_path / "updater.exe"
    installer = tmp_path / "setup.exe"
    updater.write_bytes(b"updater")
    installer.write_bytes(b"installer")
    monkeypatch.setattr(update_service.os, "name", "nt")

    with pytest.raises(UpdateError, match="Unsupported release version"):
        launch_updater(updater, installer, "latest")


def test_manager_shows_failed_installer_status() -> None:
    window = type(
        "Window",
        (),
        {"update_status": _StringValue(), "update_status_label": _StatusLabel()},
    )()

    ManagerWindow._show_installer_status(
        window,
        InstallerStatus(
            state="failed",
            version="0.5.6",
            message="Service could not be restarted.",
        ),
    )

    assert window.update_status.value == (
        "Update to version 0.5.6 failed: Service could not be restarted."
    )
    assert window.update_status_label.style == "Error.TLabel"
