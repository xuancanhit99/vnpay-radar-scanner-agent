from radar_agent.runtime_paths import default_config_path


def test_manager_config_path_can_be_overridden(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "manager.env"
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(config_path))

    assert default_config_path(tmp_path) == config_path
