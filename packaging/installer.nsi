Unicode True
RequestExecutionLevel admin
ManifestDPIAware true

!ifndef BRAND_ICON
  !error "BRAND_ICON is required"
!endif
!define MUI_ICON "${BRAND_ICON}"
!define MUI_UNICON "${BRAND_ICON}"

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.7.5"
!endif
!ifndef APP_FILE_VERSION
  !define APP_FILE_VERSION "0.7.5.0"
!endif
!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required"
!endif
!ifndef OUTPUT_DIR
  !define OUTPUT_DIR "."
!endif

!define PRODUCT_NAME "VNPAY RADAR Scanner Agent"
!define COMPANY_NAME "VNPAY"
!define SERVICE_NAME "VNPAYRadarScannerAgent"

Name "${PRODUCT_NAME}"
Icon "${BRAND_ICON}"
UninstallIcon "${BRAND_ICON}"
OutFile "${OUTPUT_DIR}\VNPAYRadarScannerAgent-Setup-${APP_VERSION}-x64.exe"
VIProductVersion "${APP_FILE_VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName" "${COMPANY_NAME}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_NAME} Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright VNPAY"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
InstallDir "$PROGRAMFILES64\VNPAY\Radar Scanner Agent"
InstallDirRegKey HKLM "Software\VNPAY\RadarScannerAgent" "InstallDirectory"
BrandingText "VNPAY RADAR"
ShowInstDetails show
ShowUninstDetails show
SetCompressor /SOLID lzma

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\radar-scanner-manager.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open RADAR Scanner Manager"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  IfSilent 0 installer_init_done
  ${GetParameters} $R0
  ${GetOptions} $R0 "/UPDATER_CHILD" $R1
  IfErrors bootstrap_updater installer_init_done

bootstrap_updater:
  SetShellVarContext all
  CreateDirectory "$APPDATA\VNPAY\RadarScannerAgent\updates"
  SetOutPath "$APPDATA\VNPAY\RadarScannerAgent\updates"
  File /oname=radar-scanner-updater-${APP_VERSION}.exe "${SOURCE_DIR}\radar-scanner-updater.exe"
  ClearErrors
  Exec '"$APPDATA\VNPAY\RadarScannerAgent\updates\radar-scanner-updater-${APP_VERSION}.exe" --installer "$EXEPATH" --version "${APP_VERSION}"'
  IfErrors updater_bootstrap_failed updater_bootstrap_done

updater_bootstrap_failed:
  SetRegView 64
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateState" "failed"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "failed"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateMessage" "Could not start the update progress window."

updater_bootstrap_done:
  Quit

installer_init_done:
FunctionEnd

Section "RADAR Scanner Agent" SEC_MAIN
  SetShellVarContext all
  SetRegView 64
  StrCpy $R7 "Setup did not complete."
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateState" "installing"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "preparing"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateMessage" ""
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "closing_manager"
  ; Do not use /T here: Setup is launched by Manager and is therefore its child process.
  nsExec::ExecToStack 'taskkill.exe /IM "radar-scanner-manager.exe" /F'
  Pop $0
  Pop $1
  nsExec::ExecToStack 'powershell.exe -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 2; if (Get-Process -Name radar-scanner-manager -ErrorAction SilentlyContinue) { Get-Process -Name radar-scanner-manager -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction Stop; Start-Sleep -Seconds 2 }; if (Get-Process -Name radar-scanner-manager -ErrorAction SilentlyContinue) { exit 1 }"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    StrCpy $R7 "Could not close Scanner Manager before replacing application files."
    Abort "$R7"
  ${EndIf}

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "checking_service"
  StrCpy $R9 "0"
  nsExec::ExecToStack 'sc.exe query "${SERVICE_NAME}"'
  Pop $0
  Pop $1
  ${If} $0 == 0
    IfFileExists "$INSTDIR\${SERVICE_NAME}.xml" existing_service_ready stale_service_registration

stale_service_registration:
    WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "stopping_service"
    nsExec::ExecToStack 'sc.exe stop "${SERVICE_NAME}"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'sc.exe delete "${SERVICE_NAME}"'
    Pop $0
    Pop $1
    ${If} $0 != 0
    ${AndIf} $0 != 1072
      StrCpy $R7 "Could not remove stale ${SERVICE_NAME} registration (sc.exe exit $0)."
      Abort "$R7"
    ${EndIf}
    StrCpy $R8 "0"
stale_service_wait:
    Sleep 500
    nsExec::ExecToStack 'sc.exe query "${SERVICE_NAME}"'
    Pop $0
    Pop $1
    ${If} $0 != 0
      Goto service_precheck_complete
    ${EndIf}
    IntOp $R8 $R8 + 1
    ${If} $R8 >= 60
      StrCpy $R7 "Timed out while removing stale ${SERVICE_NAME} registration. Restart Windows and run Setup again."
      Abort "$R7"
    ${EndIf}
    Goto stale_service_wait

existing_service_ready:
    StrCpy $R9 "1"
    WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "stopping_service"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -Command "Stop-Service -Name ${SERVICE_NAME} -Force -ErrorAction Stop; (Get-Service -Name ${SERVICE_NAME}).WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))"'
    Pop $0
    ${If} $0 != 0
      StrCpy $R7 "Could not stop ${SERVICE_NAME} for upgrade."
      Abort "$R7"
    ${EndIf}
  ${EndIf}

service_precheck_complete:

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "installing_files"
  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent"
  SetRegView 64
  SetOutPath "$INSTDIR"
  IfFileExists "$INSTDIR\radar-scanner-manager.exe" 0 manager_file_ready
  ClearErrors
  Delete "$INSTDIR\radar-scanner-manager.exe"
  IfErrors manager_file_locked manager_file_ready

manager_file_locked:
  StrCpy $R7 "Scanner Manager executable is still locked. Close it and run Setup again."
  Abort "$R7"

manager_file_ready:
  File /r "${SOURCE_DIR}\*"

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "InstallDirectory" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "DisplayIcon" "$INSTDIR\radar-scanner-manager.exe,0"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "NoRepair" 1

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\VNPAY"
  CreateShortcut "$SMPROGRAMS\VNPAY\RADAR Scanner Manager.lnk" "$INSTDIR\radar-scanner-manager.exe"
  CreateShortcut "$DESKTOP\RADAR Scanner Manager.lnk" "$INSTDIR\radar-scanner-manager.exe"

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "starting_service"
  ${If} $R9 == "1"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -Command "Start-Service -Name ${SERVICE_NAME} -ErrorAction Stop; (Get-Service -Name ${SERVICE_NAME}).WaitForStatus([ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))"'
    Pop $0
    ${If} $0 != 0
      StrCpy $R7 "${SERVICE_NAME} could not be restarted. Check Windows Event Viewer and the Agent logs."
      Abort "$R7"
    ${EndIf}
  ${EndIf}

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "verifying"
  IfFileExists "$INSTDIR\radar-scanner-manager.exe" +3 0
    StrCpy $R7 "Scanner Manager executable is missing after installation."
    Abort "$R7"
  IfFileExists "$INSTDIR\radar-scanner-updater.exe" +3 0
    StrCpy $R7 "Scanner Updater executable is missing after installation."
    Abort "$R7"
  IfFileExists "$INSTDIR\agent\radar-scanner-agent.exe" +3 0
    StrCpy $R7 "Scanner Agent executable is missing after installation."
    Abort "$R7"

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateState" "success"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateStage" "completed"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateMessage" "Installation completed successfully."
  IfSilent silent_update_relaunch interactive_install_finish
silent_update_relaunch:
  Exec '"$INSTDIR\radar-scanner-manager.exe"'
interactive_install_finish:
SectionEnd

Function .onInstFailed
  SetRegView 64
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateState" "failed"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "LastUpdateMessage" "$R7"
  IfSilent 0 installer_failure_done
  IfFileExists "$INSTDIR\radar-scanner-manager.exe" 0 installer_failure_done
  Exec '"$INSTDIR\radar-scanner-manager.exe"'
installer_failure_done:
FunctionEnd

Section "Uninstall"
  SetShellVarContext all
  SetRegView 64
  nsExec::ExecToStack 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\uninstall-service.ps1" -KeepProgramFiles'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Could not remove ${SERVICE_NAME}. Application files were preserved.$\r$\n$\r$\n$1"
    Abort
  ${EndIf}
  Delete "$DESKTOP\RADAR Scanner Manager.lnk"
  Delete "$SMPROGRAMS\VNPAY\RADAR Scanner Manager.lnk"
  RMDir "$SMPROGRAMS\VNPAY"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent"
  DeleteRegKey HKLM "Software\VNPAY\RadarScannerAgent"
  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent"
  SetRegView 64
  RMDir /r "$INSTDIR"
SectionEnd
