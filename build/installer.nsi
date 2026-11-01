; FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
; Installatore per Windows: Python e librerie inclusi, nessun permesso da amministratore.
; Prima: python build/prepara_installer.py  (crea build/stage). Poi: makensis -DVER=x.y.z build/installer.nsi
Unicode true
SetCompressor /SOLID bzip2

!define APP "FreeLaserCut"
!ifndef VER
  !define VER "0.9.1"  ; di solito arriva da: makensis -DVER=x.y.z build\installer.nsi
!endif
!define PUB "fringuello79"
!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

;--- Firma digitale (facoltativa). Esempio con un certificato nel computer (Certum, SignPath, ecc.):
;    makensis -DVER=x.y.z "-DSIGN=signtool sign /fd sha256 /tr http://time.certum.pl /td sha256 /a" build\installer.nsi
;    NSIS firma sia l'installatore sia il disinstallatore. Senza -DSIGN l'installatore esce non firmato.
!ifdef SIGN
  !finalize '${SIGN} "%1"' = 0
  !uninstfinalize '${SIGN} "%1"' = 0
!endif

Name "${APP} ${VER}"
OutFile "FreeLaserCut-${VER}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "Software\${APP}" "InstallDir"
RequestExecutionLevel user
BrandingText "${APP} ${VER} · ${PUB}"
VIProductVersion "${VER}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "CompanyName" "${PUB}"
VIAddVersionKey "FileDescription" "Installazione di ${APP}, software libero di incisione laser"
VIAddVersionKey "FileVersion" "${VER}"
VIAddVersionKey "ProductVersion" "${VER}"
VIAddVersionKey "LegalCopyright" "© 2026 ${PUB} — GNU GPL 3.0 o successiva"

!include "MUI2.nsh"
!define MUI_ICON "stage\app\freelasercut\assets\logo.ico"
!define MUI_UNICON "stage\app\freelasercut\assets\logo.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Installazione di ${APP} ${VER}"
!define MUI_WELCOMEPAGE_TEXT "FreeLaserCut è un software libero per disegnare, preparare e inviare lavori di incisione e taglio ai laser GRBL (profilo nativo per il Longer B1 40W).$\r$\n$\r$\nTutto il necessario è incluso: non serve installare Python né scaricare altro, e non servono permessi da amministratore.$\r$\n$\r$\nRicorda: un laser va usato con occhiali protettivi adatti, sotto sorveglianza e con aspirazione dei fumi."
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m freelasercut"
!define MUI_FINISHPAGE_RUN_TEXT "Avvia FreeLaserCut"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "stage\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Italian"

Section "FreeLaserCut" SecMain
  SectionIn RO
  ; aggiornamento: tolgo il programma vecchio, i dati in %APPDATA%\FreeLaserCut restano
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\licenze-terze-parti"
  SetOutPath "$INSTDIR"
  File "stage\LICENSE"
  File "stage\README.md"
  File "stage\CHANGELOG.md"
  File "stage\LICENZE-TERZE-PARTI.md"
  File /r "stage\licenze-terze-parti"
  File /r "stage\python"
  File /r "stage\app"
  WriteUninstaller "$INSTDIR\Disinstalla FreeLaserCut.exe"

  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-m freelasercut" "$INSTDIR\app\freelasercut\assets\logo.ico" 0 SW_SHOWNORMAL "" "Software libero di incisione laser"
  CreateShortcut "$SMPROGRAMS\${APP}\Disinstalla ${APP}.lnk" "$INSTDIR\Disinstalla FreeLaserCut.exe"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-m freelasercut" "$INSTDIR\app\freelasercut\assets\logo.ico" 0 SW_SHOWNORMAL "" "Software libero di incisione laser"

  ; i progetti .flcut si aprono con un doppio clic
  WriteRegStr HKCU "Software\Classes\.flcut" "" "FreeLaserCut.Progetto"
  WriteRegStr HKCU "Software\Classes\FreeLaserCut.Progetto" "" "Progetto FreeLaserCut"
  WriteRegStr HKCU "Software\Classes\FreeLaserCut.Progetto\DefaultIcon" "" "$INSTDIR\app\freelasercut\assets\logo.ico"
  WriteRegStr HKCU "Software\Classes\FreeLaserCut.Progetto\shell\open\command" "" '"$INSTDIR\python\pythonw.exe" -m freelasercut "%1"'

  WriteRegStr HKCU "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "${APP} ${VER}"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VER}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "${PUB}"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\app\freelasercut\assets\logo.ico"
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Disinstalla FreeLaserCut.exe"'
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\CHANGELOG.md"
  Delete "$INSTDIR\LICENZE-TERZE-PARTI.md"
  RMDir /r "$INSTDIR\licenze-terze-parti"
  Delete "$INSTDIR\Disinstalla FreeLaserCut.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Classes\.flcut"
  DeleteRegKey HKCU "Software\Classes\FreeLaserCut.Progetto"
  DeleteRegKey HKCU "${UNINST}"
  DeleteRegKey HKCU "Software\${APP}"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd
