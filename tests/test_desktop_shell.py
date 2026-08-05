import os
import uuid
from pathlib import Path

import pytest

from radar_agent.desktop_shell import SingleInstance
from radar_agent.desktop_theme import BACKGROUND, INPUT, SURFACE


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


def test_desktop_entrypoints_set_shell_identity_before_qt_application() -> None:
    source_root = Path(__file__).parents[1] / "src" / "radar_agent"

    for entrypoint in ("manager.py", "updater.py"):
        source = (source_root / entrypoint).read_text(encoding="utf-8")
        main = source.split("def main() -> None:", maxsplit=1)[1]
        assert main.index("set_windows_app_user_model_id(") < main.index("QApplication(")
