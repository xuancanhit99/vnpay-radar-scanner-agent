import os

import pytest

from radar_agent.config_store import (
    load_settings,
    plaintext_bootstrap,
    save_settings,
)
from radar_agent.settings import AgentSettings


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_save_settings_uses_dpapi_without_plaintext_secret(tmp_path) -> None:
    config_path = tmp_path / ".env"
    settings = AgentSettings(
        _env_file=None,
        id="windows-lab-02",
        display_name="Windows Lab 02",
        client_secret="new-secret",
        database_path=tmp_path / "agent.db",
    )

    secret_file = save_settings(
        settings,
        config_path,
        client_secret="new-secret",
        machine_scope=False,
    )

    content = config_path.read_text(encoding="utf-8")
    assert "new-secret" not in content
    assert "RADAR_AGENT_CLIENT_SECRET_FILE=" in content
    assert load_settings(config_path).resolved_client_secret() == "new-secret"
    assert secret_file.exists()


def test_plaintext_bootstrap_is_only_used_for_service_install() -> None:
    settings = AgentSettings(_env_file=None, client_secret="bootstrap-secret")

    content = plaintext_bootstrap(settings, "bootstrap-secret")

    assert "RADAR_AGENT_CLIENT_SECRET=bootstrap-secret" in content
    assert "RADAR_AGENT_CLIENT_SECRET_FILE=" not in content


def test_machine_scope_save_secures_the_dpapi_file(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / ".env"
    secured: list[object] = []

    def fake_protect(secret, destination, *, scope) -> None:
        assert secret == "machine-secret"
        assert scope == "machine"
        destination.write_bytes(b"protected")

    monkeypatch.setattr("radar_agent.config_store.protect_secret", fake_protect)
    monkeypatch.setattr(
        "radar_agent.config_store._secure_machine_secret",
        lambda path: secured.append(path),
    )
    settings = AgentSettings(_env_file=None, client_secret="machine-secret")

    secret_file = save_settings(
        settings,
        config_path,
        client_secret="machine-secret",
        machine_scope=True,
    )

    assert secured == [secret_file]
