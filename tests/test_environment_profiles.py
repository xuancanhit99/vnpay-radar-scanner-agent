from pathlib import Path

import pytest

from radar_agent.environment_profiles import (
    CUSTOM,
    DEVELOPMENT,
    UAT,
    database_path_for_environment,
    infer_environment,
    normalize_radar_origin,
    resolve_environment,
)


def test_known_urls_are_inferred_as_presets() -> None:
    assert infer_environment("https://radar.vnpay.dev/") == DEVELOPMENT
    assert infer_environment("https://radar.vnpaytest.vn") == UAT
    assert infer_environment("https://radar.example.vn") == CUSTOM


def test_radar_origin_is_normalized_and_rejects_credentials() -> None:
    assert normalize_radar_origin("HTTPS://RADAR.VNPAYTEST.VN:443/") == (
        "https://radar.vnpaytest.vn"
    )
    with pytest.raises(ValueError, match="must not contain credentials"):
        normalize_radar_origin("https://user:password@radar.example.vn")


def test_preset_rejects_a_mismatched_url() -> None:
    with pytest.raises(ValueError, match="does not match"):
        resolve_environment(UAT, "https://radar.vnpay.dev")


def test_environment_databases_are_isolated(tmp_path: Path) -> None:
    development = database_path_for_environment(
        tmp_path, DEVELOPMENT, "https://radar.vnpay.dev"
    )
    uat = database_path_for_environment(tmp_path, UAT, "https://radar.vnpaytest.vn")
    custom_a = database_path_for_environment(tmp_path, CUSTOM, "https://radar-a.example.vn")
    custom_b = database_path_for_environment(tmp_path, CUSTOM, "https://radar-b.example.vn")

    assert development == tmp_path / "profiles" / "development" / "agent.db"
    assert uat == tmp_path / "profiles" / "uat" / "agent.db"
    assert custom_a.parent.name.startswith("custom-")
    assert custom_a == database_path_for_environment(
        tmp_path, CUSTOM, "https://radar-a.example.vn/"
    )
    assert len({development, uat, custom_a, custom_b}) == 4


def test_existing_development_outbox_is_preserved(tmp_path: Path) -> None:
    legacy = tmp_path / "agent.db"
    legacy.touch()

    assert (
        database_path_for_environment(tmp_path, DEVELOPMENT, "https://radar.vnpay.dev")
        == legacy
    )
