from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    device_model: str = "Xiaomi 13"
    database_path: Path = Path("./agent.db")
    verify_tls: bool = True
    poll_wait_seconds: int = Field(default=20, ge=0, le=25)
    lease_renew_interval_seconds: int = Field(default=15, ge=5, le=30)
    scanner_timeout_seconds: int = Field(default=400, ge=30, le=900)
    retry_delay_seconds: int = Field(default=5, ge=1, le=60)

    def validate_runtime(self) -> None:
        if not self.client_secret:
            raise ValueError("RADAR_AGENT_CLIENT_SECRET is required")
