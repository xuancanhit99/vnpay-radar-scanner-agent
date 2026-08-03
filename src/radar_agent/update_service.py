import ctypes
import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

LATEST_RELEASE_API = (
    "https://api.github.com/repos/xuancanhit99/" "vnpay-radar-scanner-agent/releases/latest"
)
MAX_INSTALLER_BYTES = 100 * 1024 * 1024
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    available: bool
    release_url: str
    installer_name: str
    installer_url: str
    sha256: str


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise UpdateError(f"Unsupported release version: {value}")
    return tuple(int(part) for part in match.groups())


def _require_github_https_url(value: object, *, label: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    trusted_host = hostname in {"api.github.com", "github.com"} or hostname.endswith(
        ".githubusercontent.com"
    )
    if parsed.scheme != "https" or not trusted_host:
        raise UpdateError(f"{label} must use a trusted GitHub HTTPS URL")
    return url


def _asset_url(assets: object, name: str) -> str:
    if not isinstance(assets, list):
        raise UpdateError("GitHub release assets are invalid")
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == name:
            return _require_github_https_url(
                asset.get("browser_download_url"),
                label=name,
            )
    raise UpdateError(f"GitHub release is missing {name}")


def _checksum_for(content: str, installer_name: str) -> str:
    for line in content.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip("*") == installer_name:
            checksum = parts[0].lower()
            if not _SHA256_PATTERN.fullmatch(checksum):
                break
            return checksum
    raise UpdateError(f"Release checksum does not contain {installer_name}")


def check_for_update(
    current_version: str,
    *,
    client: httpx.Client | None = None,
) -> UpdateInfo:
    owns_client = client is None
    http_client = client or httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0),
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        response = http_client.get(
            LATEST_RELEASE_API,
            headers={"User-Agent": f"VNPAY-RADAR-Scanner-Manager/{current_version}"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
            raise UpdateError("GitHub latest release response is invalid")

        tag_name = str(payload.get("tag_name") or "")
        latest_tuple = _parse_version(tag_name)
        latest_version = ".".join(str(part) for part in latest_tuple)
        current_tuple = _parse_version(current_version)
        installer_name = f"VNPAYRadarScannerAgent-Setup-{latest_version}-x64.exe"
        checksum_name = f"VNPAYRadarScannerAgent-{latest_version}-SHA256SUMS.txt"
        installer_url = _asset_url(payload.get("assets"), installer_name)
        checksum_url = _asset_url(payload.get("assets"), checksum_name)

        checksum_response = http_client.get(checksum_url)
        checksum_response.raise_for_status()
        if len(checksum_response.content) > 16 * 1024:
            raise UpdateError("Release checksum file is unexpectedly large")

        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_version,
            available=latest_tuple > current_tuple,
            release_url=_require_github_https_url(
                payload.get("html_url"),
                label="Release page",
            ),
            installer_name=installer_name,
            installer_url=installer_url,
            sha256=_checksum_for(checksum_response.text, installer_name),
        )
    except (httpx.HTTPError, ValueError) as exc:
        raise UpdateError(f"Unable to check GitHub Releases: {exc}") from exc
    finally:
        if owns_client:
            http_client.close()


def download_installer(
    update: UpdateInfo,
    destination_directory: Path,
    *,
    progress: Callable[[int, int | None], None] | None = None,
    client: httpx.Client | None = None,
) -> Path:
    if not update.available:
        raise UpdateError("No newer release is available")
    if Path(update.installer_name).name != update.installer_name:
        raise UpdateError("Installer name is invalid")
    _require_github_https_url(update.installer_url, label="Installer")

    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / update.installer_name
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.unlink(missing_ok=True)

    owns_client = client is None
    http_client = client or httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(120.0, connect=15.0),
    )
    received = 0
    digest = hashlib.sha256()
    try:
        with http_client.stream(
            "GET",
            update.installer_url,
            headers={"User-Agent": f"VNPAY-RADAR-Scanner-Manager/{update.current_version}"},
        ) as response:
            response.raise_for_status()
            _require_github_https_url(str(response.url), label="Installer response")
            content_length_header = response.headers.get("content-length")
            total = int(content_length_header) if content_length_header else None
            if total is not None and total > MAX_INSTALLER_BYTES:
                raise UpdateError("Installer exceeds the maximum allowed size")

            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > MAX_INSTALLER_BYTES:
                        raise UpdateError("Installer exceeds the maximum allowed size")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(received, total)

        if digest.hexdigest().lower() != update.sha256.lower():
            raise UpdateError("Downloaded installer SHA-256 does not match the release checksum")
        os.replace(temporary, destination)
        return destination
    except (httpx.HTTPError, OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"Unable to download update: {exc}") from exc
    except UpdateError:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            http_client.close()


def launch_installer(installer: Path) -> None:
    if os.name != "nt":
        raise UpdateError("Automatic installation is only supported on Windows")
    if not installer.is_file():
        raise UpdateError(f"Installer not found: {installer}")
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        str(installer),
        "/S",
        str(installer.parent),
        1,
    )
    if result <= 32:
        raise UpdateError(f"Unable to start elevated installer (Windows error {result})")
