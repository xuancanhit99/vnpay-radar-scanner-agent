from pathlib import Path

INSTALLER_SCRIPT = Path(__file__).parents[1] / "packaging" / "installer.nsi"
UNINSTALL_SCRIPT = Path(__file__).parents[1] / "packaging" / "uninstall-service.ps1"


def test_silent_update_relaunches_manager() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert "IfSilent silent_update_relaunch interactive_install_finish" in script
    assert "silent_update_relaunch:" in script
    assert "Exec '\"$INSTDIR\\radar-scanner-manager.exe\"'" in script


def test_installer_recovers_stale_service_registration() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'IfFileExists "$INSTDIR\\${SERVICE_NAME}.xml"' in script
    assert "stale_service_registration:" in script
    assert "sc.exe delete" in script
    assert "stale_service_wait:" in script


def test_uninstaller_preserves_files_when_service_removal_fails() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    uninstall_call = script.index("uninstall-service.ps1")
    error_check = script.index("${If} $0 != 0", uninstall_call)
    remove_files = script.index('RMDir /r "$INSTDIR"', uninstall_call)
    assert uninstall_call < error_check < remove_files
    assert "Application files were preserved" in script


def test_service_uninstall_waits_until_registration_is_removed() -> None:
    script = UNINSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "function Wait-ServiceRemoval" in script
    assert "Wait-ServiceRemoval -Name $serviceName" in script
