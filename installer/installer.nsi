; GIGO QC - NSIS Installer Script
; Build: makensis installer.nsi
; Requires: NSIS 3.x with MUI2

!include "MUI2.nsh"
!include "FileFunc.nsh"

;-------------------------------------
; Metadata
;-------------------------------------
!define APP_NAME      "GIGO QC"
!define APP_VERSION   "1.0.0"
!define APP_PUBLISHER "Kangwon National University"
!define APP_URL       "https://github.com/white4477-spec/gigo-qc"
!define APP_EXE       "GIGO-QC.exe"
!define APP_REG_KEY   "Software\GIGO-QC"
!define UNINST_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\GIGO-QC"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "GIGO-QC-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\GIGO-QC"
InstallDirRegKey HKCU "${APP_REG_KEY}" "InstallDir"
RequestExecutionLevel user   ; 관리자 권한 불필요 (사용자 폴더 설치)
SetCompressor /SOLID lzma
Unicode true

;-------------------------------------
; Modern UI
;-------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON   "icon.ico"
!define MUI_UNICON "icon.ico"

; 한국어 UI
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "지금 GIGO QC 실행"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "README 열기"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "English"

;-------------------------------------
; Version Info
;-------------------------------------
VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName"    "${APP_NAME}"
VIAddVersionKey "CompanyName"    "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "Lacey Carbon Grid QC"
VIAddVersionKey "FileVersion"    "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "© 2026 ${APP_PUBLISHER}"

;-------------------------------------
; Install
;-------------------------------------
Section "GIGO QC (필수)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; PyInstaller --onedir 산출물 전체 복사
  File /r "payload\*.*"

  ; 시작 메뉴
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\제거.lnk"        "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\README.lnk"       "$INSTDIR\README.md"

  ; 바탕화면 바로가기
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

  ; 레지스트리 (제거 프로그램 등록)
  WriteRegStr HKCU "${APP_REG_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${APP_REG_KEY}" "Version"    "${APP_VERSION}"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName"     "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout"    "${APP_URL}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ; 설치 크기 기록
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

;-------------------------------------
; Uninstall
;-------------------------------------
Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${APP_REG_KEY}"
  DeleteRegKey HKCU "${UNINST_KEY}"
SectionEnd
