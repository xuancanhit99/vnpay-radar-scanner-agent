import os
import sys
from pathlib import Path

SERVICE_NAME = "VNPAYRadarScannerAgent"
PRODUCT_DIRECTORY = Path("VNPAY") / "RadarScannerAgent"


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def program_data_directory() -> Path:
    return Path(os.environ.get("ProgramData", "C:/ProgramData")) / PRODUCT_DIRECTORY


def portable_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / PRODUCT_DIRECTORY


def is_installed_package(root: Path | None = None) -> bool:
    root = (root or package_root()).resolve()
    candidates = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            root.relative_to(Path(candidate).resolve())
            return True
        except ValueError:
            continue
    return False


def default_config_path(root: Path | None = None) -> Path:
    explicit_config = os.environ.get("RADAR_AGENT_MANAGER_CONFIG")
    if explicit_config:
        return Path(explicit_config).expanduser()
    installed_config = program_data_directory() / ".env"
    if installed_config.exists() or is_installed_package(root):
        return installed_config
    return portable_data_directory() / ".env"


def worker_executable(root: Path | None = None) -> Path:
    root = root or package_root()
    candidates = [
        root / "agent" / "radar-scanner-agent.exe",
        root / "radar-scanner-agent.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def service_log_path() -> Path:
    return program_data_directory() / "logs" / f"{SERVICE_NAME}.err.log"
