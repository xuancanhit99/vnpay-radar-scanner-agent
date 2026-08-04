from pathlib import Path

INSTALLER_SCRIPT = Path(__file__).parents[1] / "packaging" / "installer.nsi"


def test_silent_update_relaunches_manager() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "IfSilent silent_update_relaunch interactive_install_finish" in script
    assert "silent_update_relaunch:" in script
    assert "Exec '\"$INSTDIR\\radar-scanner-manager.exe\"'" in script
