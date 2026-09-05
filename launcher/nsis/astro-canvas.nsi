; Windows installer for the click-to-run launcher (design 4.3 tier 2).
;
;   makensis -DVERSION=0.1.0a1 -DLAUNCHER=..\dist\astro-canvas-launcher-windows-x64.exe \
;            -DOUTFILE=..\dist\astro-canvas-0.1.0a1-setup.exe astro-canvas.nsi
;
; What it installs is one PyApp binary plus a shortcut. The Python interpreter and the wheels are
; *not* in this installer: PyApp fetches them on the first launch, which is what keeps the
; download small and lets a new release ship without re-signing anything but the launcher.
;
; Per-user install by design (HKCU, $LOCALAPPDATA): no administrator prompt, and a short install
; path - a venv full of numpy and astropy DLLs runs into the 260-character MAX_PATH limit if it
; sits under a deep Program Files path (research R4 section 7).

Unicode true
ManifestDPIAware true
RequestExecutionLevel user

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef LAUNCHER
  !define LAUNCHER "..\dist\astro-canvas-launcher-windows-x64.exe"
!endif
!ifndef OUTFILE
  !define OUTFILE "..\dist\astro-canvas-${VERSION}-setup.exe"
!endif

!define APPNAME "Astro Canvas"
!define PUBLISHER "Bin Liu"
!define HOMEPAGE "https://github.com/lblogan14/astro-canvas"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AstroCanvas"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\astro-canvas"
InstallDirRegKey HKCU "Software\AstroCanvas" "InstallDir"
SetCompressor /SOLID lzma
BrandingText "${APPNAME} ${VERSION}"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "astro-canvas.ico"
!define MUI_UNICON "astro-canvas.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\astro-canvas.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "open --first-run"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME}"
!define MUI_FINISHPAGE_LINK "Documentation"
!define MUI_FINISHPAGE_LINK_LOCATION "${HOMEPAGE}"

!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

VIProductVersion "0.1.0.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "Node-based canvas for astronomical data"
VIAddVersionKey "LegalCopyright" "MIT"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

Section "Astro Canvas" SecApp
  SetOutPath "$INSTDIR"
  ; One file: the launcher. It brings its own Python on first run.
  File /oname=astro-canvas.exe "${LAUNCHER}"
  File /nonfatal "astro-canvas.ico"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  ; `open` reuses a server that is already running instead of fighting it for the port.
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\astro-canvas.exe" "open" \
    "$INSTDIR\astro-canvas.ico" 0 SW_SHOWMINIMIZED "" "Node-based canvas for astronomical data"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\astro-canvas.exe" "open" \
    "$INSTDIR\astro-canvas.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\uninstall.exe"

  WriteRegStr HKCU "Software\AstroCanvas" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGKEY}" "DisplayIcon" "$INSTDIR\astro-canvas.exe"
  WriteRegStr HKCU "${REGKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${REGKEY}" "URLInfoAbout" "${HOMEPAGE}"
  WriteRegStr HKCU "${REGKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${REGKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegStr HKCU "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${REGKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${REGKEY}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  ; PyApp keeps its downloaded interpreter and wheels outside $INSTDIR; `self remove` is the
  ; only thing that knows where, so it runs before the files go.
  ExecWait '"$INSTDIR\astro-canvas.exe" self remove' $0

  Delete "$INSTDIR\astro-canvas.exe"
  Delete "$INSTDIR\astro-canvas.ico"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"

  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "Software\AstroCanvas"

  ; The workspace (<Documents>\AstroCanvas) holds the user's workflows and data: never touched.
  DetailPrint "Your workspace under Documents\AstroCanvas was left in place."
SectionEnd
