from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from radar_agent.secret_store import unprotect_secret


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RADAR_AGENT_",
        extra="ignore",
    )

    base_url: str = "https://radar.vnpay.dev"
    id: str = Field(default="windows-canhvx-01", pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = "Windows Scanner 01"
    scanner_url: str = "http://127.0.0.1:8000"
    token_url: str = (
        "https://idsafe.vnpaytest.vn/realms/VNPAY-TEST/protocol/openid-connect/token"
    )
    client_id: str = "vnpay-radar-agent"
    client_secret: str = ""
    client_secret_file: Path | None = None
    device_model: str = "Xiaomi 13"
    database_path: Path = Path("./agent.db")
    verify_tls: bool = True
    poll_wait_seconds: int = Field(default=20, ge=0, le=25)
    lease_renew_interval_seconds: int = Field(default=15, ge=5, le=30)
    scanner_timeout_seconds: int = Field(default=400, ge=30, le=900)
    retry_delay_seconds: int = Field(default=5, ge=1, le=60)

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

    def validate_runtime(self) -> None:
        self.resolved_client_secret()
