from pathlib import Path

INSTALLER_SCRIPT = Path(__file__).parents[1] / "packaging" / "installer.nsi"
INSTALL_SERVICE_SCRIPT = Path(__file__).parents[1] / "packaging" / "install-service.ps1"
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


def test_manager_hands_download_to_progress_updater() -> None:
    manager_script = (
        Path(__file__).parents[1] / "src" / "radar_agent" / "manager.py"
    ).read_text(encoding="utf-8")
    method = manager_script.split("def _launch_downloaded_update", maxsplit=1)[1]
    method = method.split("\n    def ", maxsplit=1)[0]

    assert "launch_updater(updater, installer" in method
    assert "launch_installer(installer)" in method
    assert "self.destroy" not in method


def test_installer_does_not_kill_its_own_process_tree() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    taskkill_lines = [line for line in script.splitlines() if "taskkill.exe" in line]
    assert taskkill_lines
    assert all(" /T " not in line for line in taskkill_lines)


def test_installer_waits_for_manager_file_to_be_released() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    close_manager = script.index("Get-Process -Name radar-scanner-manager")
    delete_manager = script.index('Delete "$INSTDIR\\radar-scanner-manager.exe"')
    copy_files = script.index('File /r "${SOURCE_DIR}\\*"')
    assert close_manager < delete_manager < copy_files
    assert "manager_file_locked:" in script
    assert "Scanner Manager executable is still locked" in script


def test_manager_uses_reinstall_service_label() -> None:
    manager_script = (
        Path(__file__).parents[1] / "src" / "radar_agent" / "manager.py"
    ).read_text(encoding="utf-8")

    assert 'text="Install / Reinstall"' in manager_script
    assert "Install / upgrade" not in manager_script


def test_silent_setup_bootstraps_progress_updater_for_older_manager() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'IfErrors bootstrap_updater installer_init_done' in script
    assert 'File /oname=radar-scanner-updater-${APP_VERSION}.exe' in script
    assert '$APPDATA\\VNPAY\\RadarScannerAgent\\updates' in script
    assert "$COMMONAPPDATA" not in script
    assert '--installer "$EXEPATH" --version "${APP_VERSION}"' in script
    assert '"/UPDATER_CHILD"' in script


def test_installer_reports_real_progress_stages() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    for stage in (
        "preparing",
        "closing_manager",
        "checking_service",
        "stopping_service",
        "installing_files",
        "starting_service",
        "verifying",
        "completed",
    ):
        assert f'"LastUpdateStage" "{stage}"' in script


def test_installer_verifies_all_application_executables() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert 'IfFileExists "$INSTDIR\\radar-scanner-manager.exe"' in script
    assert 'IfFileExists "$INSTDIR\\radar-scanner-updater.exe"' in script
    assert 'IfFileExists "$INSTDIR\\agent\\radar-scanner-agent.exe"' in script


def test_installer_uses_official_brand_icon() -> None:
    script = INSTALLER_SCRIPT.read_text(encoding="utf-8")

    assert '!define MUI_ICON "${BRAND_ICON}"' in script
    assert 'Icon "${BRAND_ICON}"' in script
    assert 'UninstallIcon "${BRAND_ICON}"' in script
    assert '"DisplayIcon" "$INSTDIR\\radar-scanner.ico,0"' in script
    assert '"$INSTDIR\\radar-scanner.ico" 0' in script
    assert "SHChangeNotify" in script


def test_release_bundle_contains_standalone_shell_icon() -> None:
    build_script = (INSTALLER_SCRIPT.parent / "build.ps1").read_text(encoding="utf-8")
    manager_spec = (INSTALLER_SCRIPT.parent / "radar-scanner-manager.spec").read_text(
        encoding="utf-8"
    )
    updater_spec = (INSTALLER_SCRIPT.parent / "radar-scanner-updater.spec").read_text(
        encoding="utf-8"
    )

    assert '"radar-scanner.ico"' in build_script
    assert '"icon.ico"' in manager_spec
    assert '"icon.ico"' in updater_spec


def test_service_installer_uses_environment_specific_outbox() -> None:
    script = INSTALL_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert "RADAR_AGENT_ENVIRONMENT" in script
    assert '"profiles\\$environment\\agent.db"' in script
    assert "custom-[0-9a-f]{12}" in script
    assert "Test-Path -LiteralPath (Join-Path $DataDirectory 'agent.db')" in script
