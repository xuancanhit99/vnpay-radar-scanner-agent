import asyncio
import time

import httpx

from radar_agent.settings import AgentSettings


class TokenProvider:
    def __init__(self, settings: AgentSettings, client: httpx.AsyncClient):
        self._settings = settings
        self._client = client
        self._access_token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.monotonic() < self._expires_at - 30:
            return self._access_token

        async with self._lock:
            if (
                not force_refresh
                and self._access_token
                and time.monotonic() < self._expires_at - 30
            ):
                return self._access_token
            response = await self._client.post(
                self._settings.token_url,
                data={
                    "client_id": self._settings.client_id,
                    "client_secret": self._settings.client_secret,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._expires_at = time.monotonic() + int(payload.get("expires_in", 60))
            return self._access_token
