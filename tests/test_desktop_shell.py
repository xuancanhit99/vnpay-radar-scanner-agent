import os
import uuid

import pytest

from radar_agent.desktop_shell import SingleInstance, create_radar_icon


def test_radar_icon_has_expected_size_and_alpha_channel() -> None:
    icon = create_radar_icon(48)

    assert icon.size == (48, 48)
    assert icon.mode == "RGBA"


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_single_instance_releases_named_mutex() -> None:
    name = rf"Local\VNPAYRadarScannerManagerTest-{uuid.uuid4()}"
    first = SingleInstance(name)
    duplicate = SingleInstance(name)
    replacement = SingleInstance(name)

    try:
        assert first.acquire() is True
        assert duplicate.acquire() is False
        first.close()
        assert replacement.acquire() is True
    finally:
        first.close()
        duplicate.close()
        replacement.close()
