import os

import pytest

from radar_agent.secret_store import protect_secret, unprotect_secret
from radar_agent.settings import AgentSettings


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_machine_scope_round_trip(tmp_path) -> None:
    secret_file = tmp_path / "client-secret.dpapi"

    protect_secret("service-secret", secret_file)

    assert unprotect_secret(secret_file) == "service-secret"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_settings_resolve_secret_from_dpapi_file(tmp_path) -> None:
    secret_file = tmp_path / "client-secret.dpapi"
    protect_secret("service-secret", secret_file)
    settings = AgentSettings(client_secret="", client_secret_file=secret_file)

    assert settings.resolved_client_secret() == "service-secret"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_current_user_scope_round_trip(tmp_path) -> None:
    secret_file = tmp_path / "client-secret-user.dpapi"

    protect_secret("portable-secret", secret_file, scope="user")

    assert unprotect_secret(secret_file) == "portable-secret"


def test_plaintext_secret_remains_available_for_console_mode() -> None:
    settings = AgentSettings(client_secret="console-secret", client_secret_file=None)

    assert settings.resolved_client_secret() == "console-secret"
