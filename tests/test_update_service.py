import hashlib

import httpx
import pytest

from radar_agent import update_service
from radar_agent.update_service import (
    UpdateError,
    check_for_update,
    download_installer,
    launch_installer,
)


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
