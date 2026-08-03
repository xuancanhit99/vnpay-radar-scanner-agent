import os
import subprocess
from pathlib import Path

from radar_agent.secret_store import protect_secret, unprotect_secret
from radar_agent.settings import AgentSettings

_CONFIG_FIELDS = (
    ("base_url", "RADAR_AGENT_BASE_URL"),
    ("id", "RADAR_AGENT_ID"),
    ("display_name", "RADAR_AGENT_DISPLAY_NAME"),
    ("scanner_url", "RADAR_AGENT_SCANNER_URL"),
    ("token_url", "RADAR_AGENT_TOKEN_URL"),
    ("client_id", "RADAR_AGENT_CLIENT_ID"),
    ("device_model", "RADAR_AGENT_DEVICE_MODEL"),
    ("database_path", "RADAR_AGENT_DATABASE_PATH"),
    ("verify_tls", "RADAR_AGENT_VERIFY_TLS"),
    ("poll_wait_seconds", "RADAR_AGENT_POLL_WAIT_SECONDS"),
    ("lease_renew_interval_seconds", "RADAR_AGENT_LEASE_RENEW_INTERVAL_SECONDS"),
    ("scanner_timeout_seconds", "RADAR_AGENT_SCANNER_TIMEOUT_SECONDS"),
    ("retry_delay_seconds", "RADAR_AGENT_RETRY_DELAY_SECONDS"),
)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _secure_machine_secret(secret_file: Path) -> None:
    result = subprocess.run(
        [
            "icacls.exe",
            str(secret_file),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:F",
            "*S-1-5-32-544:F",
        ],
        capture_output=True,
        text=True,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise OSError(f"Could not secure the DPAPI secret file: {detail}")


def load_settings(config_path: Path) -> AgentSettings:
    env_file: Path | None = config_path if config_path.exists() else None
    return AgentSettings(_env_file=env_file)


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return value.as_posix()
    text = str(value)
    if any(character in text for character in (" ", "#", '"', "'")):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def serialize_settings(
    settings: AgentSettings,
    *,
    secret_file: Path | None,
    plaintext_secret: str | None = None,
) -> str:
    lines = [
        f"{environment_name}={_format_value(getattr(settings, field_name))}"
        for field_name, environment_name in _CONFIG_FIELDS
    ]
    if plaintext_secret is not None:
        lines.append(f"RADAR_AGENT_CLIENT_SECRET={_format_value(plaintext_secret)}")
    elif secret_file is not None:
        lines.append(f"RADAR_AGENT_CLIENT_SECRET_FILE={secret_file.as_posix()}")
    return "\n".join(lines) + "\n"


def save_settings(
    settings: AgentSettings,
    config_path: Path,
    *,
    client_secret: str = "",
    machine_scope: bool,
) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    secret_file = config_path.parent / "client-secret.dpapi"

    resolved_secret = client_secret.strip()
    if not resolved_secret and settings.client_secret:
        resolved_secret = settings.client_secret
    if not resolved_secret and settings.client_secret_file is not None:
        source = settings.client_secret_file
        if source.exists() and source.resolve() != secret_file.resolve():
            resolved_secret = unprotect_secret(source)

    if resolved_secret:
        protect_secret(
            resolved_secret,
            secret_file,
            scope="machine" if machine_scope else "user",
        )
        if machine_scope:
            _secure_machine_secret(secret_file)
    elif not secret_file.exists():
        raise ValueError("Client secret is required before saving the configuration")

    content = serialize_settings(settings, secret_file=secret_file)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, config_path)
    return secret_file


def plaintext_bootstrap(settings: AgentSettings, client_secret: str) -> str:
    if not client_secret:
        raise ValueError("Client secret is required to install the service")
    return serialize_settings(
        settings,
        secret_file=None,
        plaintext_secret=client_secret,
    )
