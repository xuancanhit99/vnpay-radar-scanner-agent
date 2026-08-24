from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from radar_agent.environment_profiles import (
    environment_label,
    normalize_radar_origin,
    resolve_environment,
)
from radar_agent.secret_store import unprotect_secret


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RADAR_AGENT_",
        extra="ignore",
    )

    environment: str = ""
    base_url: str = "https://radar.vnpay.dev"
    id: str = Field(default="windows-lab-01", pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = "Windows Lab 01"
    scanner_url: str = "http://127.0.0.1:8000"
    dast_enabled: bool = False
    dast_agent_id: str = ""
    dast_display_name: str = ""
    dast_engine_url: str = "http://127.0.0.1:8010"
    dast_engine_api_key: str = ""
    dast_engine_api_key_file: Path | None = None
    # Read legacy installations without failing. Centralized DAST credentials
    # are now supplied by RADAR and this file is no longer used at runtime.
    dast_principals_file: Path | None = None
    dast_poll_interval_seconds: int = Field(default=2, ge=1, le=30)
    dast_timeout_seconds: int = Field(default=2700, ge=30, le=7200)
    token_url: str = (
        "https://idsafe.vnpaytest.vn/realms/VNPAY-TEST/protocol/openid-connect/token"
    )
    client_id: str = "vnpay-radar-agent"
    client_secret: str = ""
    client_secret_file: Path | None = None
    database_path: Path = Path("./agent.db")
    verify_tls: bool = True
    heartbeat_interval_seconds: int = Field(default=10, ge=5, le=30)
    poll_wait_seconds: int = Field(default=20, ge=0, le=25)
    lease_renew_interval_seconds: int = Field(default=15, ge=5, le=30)
    scanner_timeout_seconds: int = Field(default=400, ge=30, le=900)
    retry_delay_seconds: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def resolve_environment_profile(self) -> "AgentSettings":
        self.base_url = normalize_radar_origin(self.base_url)
        self.environment = resolve_environment(self.environment, self.base_url)
        return self

    @field_validator(
        "client_secret_file",
        "dast_engine_api_key_file",
        "dast_principals_file",
        mode="before",
    )
    @classmethod
    def normalize_empty_secret_file(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def resolved_client_secret(self) -> str:
        if self.client_secret:
            return self.client_secret
        if self.client_secret_file is not None:
            secret = unprotect_secret(self.client_secret_file)
            if secret:
                return secret
        raise ValueError(
            "RADAR_AGENT_CLIENT_SECRET or RADAR_AGENT_CLIENT_SECRET_FILE is required"
        )

    @property
    def radar_origin(self) -> str:
        return normalize_radar_origin(self.base_url)

    @property
    def environment_display_name(self) -> str:
        return environment_label(self.environment)

    @property
    def resolved_dast_agent_id(self) -> str:
        return self.dast_agent_id.strip() or f"{self.id}-dast"

    @property
    def resolved_dast_display_name(self) -> str:
        return self.dast_display_name.strip() or f"{self.display_name} DAST"

    def resolved_dast_engine_api_key(self) -> str:
        if self.dast_engine_api_key:
            return self.dast_engine_api_key
        if self.dast_engine_api_key_file is not None:
            secret = unprotect_secret(self.dast_engine_api_key_file)
            if secret:
                return secret
        raise ValueError(
            "RADAR_AGENT_DAST_ENGINE_API_KEY or "
            "RADAR_AGENT_DAST_ENGINE_API_KEY_FILE is required when DAST is enabled"
        )

    def validate_runtime(self) -> None:
        self.resolved_client_secret()
        if self.dast_enabled:
            self.resolved_dast_engine_api_key()
