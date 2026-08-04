Unicode True
RequestExecutionLevel admin
ManifestDPIAware true

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.5.4"
!endif
!ifndef APP_FILE_VERSION
  !define APP_FILE_VERSION "0.5.4.0"
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

Section "RADAR Scanner Agent" SEC_MAIN
  SetShellVarContext all
  nsExec::ExecToStack 'taskkill.exe /IM "radar-scanner-manager.exe" /T /F'
  Pop $0
  Pop $1
  Sleep 1000

  StrCpy $R9 "0"
  nsExec::ExecToStack 'sc.exe query "${SERVICE_NAME}"'
  Pop $0
  Pop $1
  ${If} $0 == 0
    IfFileExists "$INSTDIR\${SERVICE_NAME}.xml" existing_service_ready stale_service_registration

stale_service_registration:
    nsExec::ExecToStack 'sc.exe stop "${SERVICE_NAME}"'
    Pop $0
    Pop $1
    nsExec::ExecToStack 'sc.exe delete "${SERVICE_NAME}"'
    Pop $0
    Pop $1
    ${If} $0 != 0
    ${AndIf} $0 != 1072
      Abort "Could not remove stale ${SERVICE_NAME} registration (sc.exe exit $0)."
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
      Abort "Timed out while removing stale ${SERVICE_NAME} registration. Restart Windows and run Setup again."
    ${EndIf}
    Goto stale_service_wait

existing_service_ready:
    StrCpy $R9 "1"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -Command "Stop-Service -Name ${SERVICE_NAME} -Force -ErrorAction Stop; (Get-Service -Name ${SERVICE_NAME}).WaitForStatus([ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))"'
    Pop $0
    ${If} $0 != 0
      Abort "Could not stop ${SERVICE_NAME} for upgrade."
    ${EndIf}
  ${EndIf}

service_precheck_complete:

  SetRegView 32
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent"
  SetRegView 64
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"

  WriteRegStr HKLM "Software\VNPAY\RadarScannerAgent" "InstallDirectory" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "Publisher" "${COMPANY_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VNPAYRadarScannerAgent" "NoRepair" 1

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\VNPAY"
  CreateShortcut "$SMPROGRAMS\VNPAY\RADAR Scanner Manager.lnk" "$INSTDIR\radar-scanner-manager.exe"
  CreateShortcut "$DESKTOP\RADAR Scanner Manager.lnk" "$INSTDIR\radar-scanner-manager.exe"

  ${If} $R9 == "1"
    nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -Command "Start-Service -Name ${SERVICE_NAME} -ErrorAction Stop; (Get-Service -Name ${SERVICE_NAME}).WaitForStatus([ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))"'
    Pop $0
    ${If} $0 != 0
      MessageBox MB_ICONSTOP "${SERVICE_NAME} could not be restarted. Check Windows Event Viewer and the Agent logs."
    ${EndIf}
  ${EndIf}

  IfSilent silent_update_relaunch interactive_install_finish
silent_update_relaunch:
  Exec '"$INSTDIR\radar-scanner-manager.exe"'
interactive_install_finish:
SectionEnd

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
