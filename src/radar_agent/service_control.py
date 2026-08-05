import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from radar_agent.runtime_paths import SERVICE_NAME, service_log_path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class ServiceState:
    installed: bool
    status: str
    start_mode: str = ""


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )


def query_service() -> ServiceState:
    if os.name != "nt":
        return ServiceState(False, "unsupported")
    script = (
        f"$s=Get-CimInstance Win32_Service -Filter \"Name='{SERVICE_NAME}'\";"
        "if($null -eq $s){exit 3};"
        "$s | Select-Object State,StartMode | ConvertTo-Json -Compress"
    )
    result = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
    if result.returncode == 3:
        return ServiceState(False, "not-installed")
    if result.returncode != 0:
        return ServiceState(False, "unknown")
    payload = json.loads(result.stdout)
    return ServiceState(True, str(payload["State"]).lower(), str(payload["StartMode"]))


def service_action(action: str) -> str:
    if action not in {"start", "stop", "restart"}:
        raise ValueError(f"Unsupported service action: {action}")
    command = {
        "start": "Start-Service",
        "stop": "Stop-Service",
        "restart": "Restart-Service",
    }[action]
    target = "Running" if action in {"start", "restart"} else "Stopped"
    script = (
        f"{command} -Name '{SERVICE_NAME}' -ErrorAction Stop;"
        f"(Get-Service -Name '{SERVICE_NAME}').WaitForStatus('{target}',"
        "[TimeSpan]::FromSeconds(30));"
        f"(Get-Service -Name '{SERVICE_NAME}').Status"
    )
    result = _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=40,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        error_log = service_log_path()
        wrapper_log = error_log.with_name(f"{SERVICE_NAME}.wrapper.log")
        raise RuntimeError(
            f"{detail}\n\nAgent logs:\n- {error_log}\n- {wrapper_log}"
        )
    return result.stdout.strip()


def install_service(package_directory: Path, config_file: Path) -> str:
    script = package_directory / "install-service.ps1"
    if not script.exists():
        raise FileNotFoundError(f"Missing service installer: {script}")
    result = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PackageDirectory",
            str(package_directory),
            "-ConfigFile",
            str(config_file),
        ],
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def read_service_log(max_lines: int = 300) -> str:
    path = service_log_path()
    if not path.exists():
        return "Service log is not available yet."
    if max_lines <= 0:
        return ""

    chunks: list[bytes] = []
    newline_count = 0
    block_size = 16 * 1024
    with path.open("rb") as log_file:
        position = log_file.seek(0, os.SEEK_END)
        while position > 0 and newline_count <= max_lines:
            read_size = min(block_size, position)
            position -= read_size
            log_file.seek(position)
            chunk = log_file.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return "\n".join(content.splitlines()[-max_lines:])
