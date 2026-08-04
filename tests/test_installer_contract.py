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


def test_silent_installer_records_result_and_reopens_manager_on_failure() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert '"LastUpdateState" "installing"' in script
    assert '"LastUpdateState" "success"' in script
    assert "Function .onInstFailed" in script
    assert '"LastUpdateState" "failed"' in script
    assert "IfSilent 0 installer_failure_done" in script
    assert "Exec '\"$INSTDIR\\radar-scanner-manager.exe\"'" in script


def test_manager_waits_for_installer_to_close_it() -> None:
    manager_script = (
        Path(__file__).parents[1] / "src" / "radar_agent" / "manager.py"
    ).read_text(encoding="utf-8")
    method = manager_script.split("def _launch_downloaded_update", maxsplit=1)[1]
    method = method.split("\n    def ", maxsplit=1)[0]

    assert "launch_installer(installer)" in method
    assert "self.destroy" not in method


def test_installer_does_not_kill_its_own_process_tree() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    taskkill_lines = [line for line in script.splitlines() if "taskkill.exe" in line]
    assert taskkill_lines
    assert all(" /T " not in line for line in taskkill_lines)
