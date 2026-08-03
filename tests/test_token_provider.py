import httpx
import pytest

from radar_agent.settings import AgentSettings
from radar_agent.token_provider import TokenProvider


@pytest.mark.asyncio
async def test_token_provider_uses_form_encoded_client_credentials(tmp_path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "token-1", "expires_in": 300})

    settings = AgentSettings(
        token_url="https://sso.example/token",
        client_secret="secret",
        database_path=tmp_path / "agent.db",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = TokenProvider(settings, client)
        first = await provider.get_token()
        second = await provider.get_token()

    assert first == second == "token-1"
    assert len(requests) == 1
    assert requests[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert b"grant_type=client_credentials" in requests[0].content
