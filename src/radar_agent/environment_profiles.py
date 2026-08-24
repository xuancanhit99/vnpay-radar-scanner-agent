from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEVELOPMENT = "development"
UAT = "uat"
CUSTOM = "custom"


@dataclass(frozen=True)
class EnvironmentPreset:
    id: str
    label: str
    base_url: str
    token_url: str


_TOKEN_URL = (
    "https://idsafe.vnpaytest.vn/realms/VNPAY-TEST/protocol/openid-connect/token"
)
ENVIRONMENT_PRESETS = (
    EnvironmentPreset(
        id=DEVELOPMENT,
        label="Development",
        base_url="https://radar.vnpay.dev",
        token_url=_TOKEN_URL,
    ),
    EnvironmentPreset(
        id=UAT,
        label="UAT",
        base_url="https://radar.vnpaytest.vn",
        token_url=_TOKEN_URL,
    ),
)
_PRESETS_BY_ID = {preset.id: preset for preset in ENVIRONMENT_PRESETS}


def normalize_radar_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("RADAR URL must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("RADAR URL must not contain credentials")

    host = parsed.hostname.lower()
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def preset_for(environment: str) -> EnvironmentPreset | None:
    return _PRESETS_BY_ID.get(environment)


def infer_environment(base_url: str) -> str:
    origin = normalize_radar_origin(base_url)
    for preset in ENVIRONMENT_PRESETS:
        if origin == normalize_radar_origin(preset.base_url):
            return preset.id
    return CUSTOM


def resolve_environment(environment: str, base_url: str) -> str:
    resolved = environment.strip().lower() if environment else infer_environment(base_url)
    if resolved not in {DEVELOPMENT, UAT, CUSTOM}:
        raise ValueError(f"Unsupported RADAR environment: {resolved}")

    preset = preset_for(resolved)
    if preset and normalize_radar_origin(base_url) != normalize_radar_origin(preset.base_url):
        raise ValueError(
            f"RADAR URL does not match the {preset.label} environment preset"
        )
    return resolved


def environment_label(environment: str) -> str:
    preset = preset_for(environment)
    return preset.label if preset else "Custom"


def environment_storage_key(environment: str, base_url: str) -> str:
    if environment != CUSTOM:
        return environment
    digest = sha256(normalize_radar_origin(base_url).encode("utf-8")).hexdigest()[:12]
    return f"custom-{digest}"


def database_path_for_environment(
    data_directory: Path,
    environment: str,
    base_url: str,
) -> Path:
    # Preserve the original DEV outbox in place on upgraded installations.
    legacy_database = data_directory / "agent.db"
    if environment == DEVELOPMENT and legacy_database.exists():
        return legacy_database
    storage_key = environment_storage_key(environment, base_url)
    return data_directory / "profiles" / storage_key / "agent.db"
