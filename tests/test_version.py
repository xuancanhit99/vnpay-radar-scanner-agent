import tomllib
from pathlib import Path

import radar_agent


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert radar_agent.__version__ == project["project"]["version"]
