import os
import uuid

import pytest

from radar_agent.desktop_shell import SingleInstance, create_radar_icon
from radar_agent.desktop_theme import BACKGROUND, INPUT, SURFACE


def test_radar_icon_has_expected_size_and_alpha_channel() -> None:
    icon = create_radar_icon(48)

    assert icon.size == (48, 48)
    assert icon.mode == "RGBA"


def test_desktop_theme_uses_light_surfaces() -> None:
    for color in (BACKGROUND, SURFACE, INPUT):
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
        assert min(red, green, blue) >= 240


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
