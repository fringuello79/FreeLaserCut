; FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
; Installatore per Windows: Python e librerie inclusi, nessun permesso da amministratore.
; Prima: python build/prepara_installer.py  (crea build/stage). Poi: makensis -DVER=x.y.z build/installer.nsi
Unicode true
SetCompressor /SOLID bzip2

!define APP "FreeLaserCut"
!ifndef VER
  !define VER "0.12.1"  ; di solito arriva da: makensis -DVER=x.y.z build\installer.nsi
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
!include "FileFunc.nsh"

; aggiornamento dal programma: FreeLaserCut avvia l'installatore con /AGGIORNA (e /D=cartella attuale).
; Allora l'installatore aspetta che FreeLaserCut si chiuda, salta le pagine già viste alla prima installazione,
; mostra solo l'avanzamento e alla fine riapre FreeLaserCut.
Var Aggiorna
!define MUI_ICON "stage\app\freelasercut\assets\logo.ico"
!define MUI_UNICON "stage\app\freelasercut\assets\logo.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Installazione di ${APP} ${VER}"
!define MUI_WELCOMEPAGE_TEXT "FreeLaserCut è un software libero per disegnare, preparare e inviare lavori di incisione e taglio ai laser GRBL (profilo nativo per il Longer B1 40W).$\r$\n$\r$\nTutto il necessario è incluso: non serve installare Python né scaricare altro, e non servono permessi da amministratore.$\r$\n$\r$\nRicorda: un laser va usato con occhiali protettivi adatti, sotto sorveglianza e con aspirazione dei fumi."
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m freelasercut"
!define MUI_FINISHPAGE_RUN_TEXT "Avvia FreeLaserCut"
!define MUI_DIRECTORYPAGE_TEXT_TOP "FreeLaserCut si installa solo per il tuo utente, nella cartella proposta qui sotto (dentro il tuo profilo, in AppData\Local\Programs): così non servono permessi da amministratore. Per aggiornare basta installare la nuova versione nella stessa cartella: progetti, profili e materiali restano.$\r$\n$\r$\nNon scegliere «Programmi» (C:\Program Files): senza permessi da amministratore lì non si può scrivere e l'installazione non riuscirebbe."

; messaggio quando un file non si può scrivere ($0 = il file)
FileErrorText "Non riesco a scrivere il file:$\r$\n$\r$\n$0$\r$\n$\r$\nDi solito succede perché FreeLaserCut è ancora aperto, oppure perché l'antivirus sta controllando i file. Chiudi FreeLaserCut, aspetta qualche secondo e premi «Riprova».$\r$\n«Interrompi» annulla l'installazione."

!define MUI_PAGE_CUSTOMFUNCTION_PRE SaltaSeAggiorna
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_PRE SaltaSeAggiorna
!insertmacro MUI_PAGE_LICENSE "stage\LICENSE"
!define MUI_PAGE_CUSTOMFUNCTION_PRE SaltaSeAggiorna
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_PAGE_CUSTOMFUNCTION_PRE SaltaSeAggiorna
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Italian"

;--- FreeLaserCut è aperto? $R0 = 1 se è in uso.
!macro FLC_IN_USO_FN UN
Function ${UN}FlcInUso
  ; Windows non lascia aprire in scrittura un programma in esecuzione: se pythonw.exe (FreeLaserCut)
  ; o python.exe (collegamento di diagnostica, server MCP) non si aprono in scrittura, sono in uso.
  ; Il file non viene modificato. (La prova con la rinomina della cartella non funziona: su Windows 10/11
  ; una cartella con un programma in esecuzione si rinomina lo stesso.)
  StrCpy $R0 0
  IfFileExists "$INSTDIR\python\pythonw.exe" 0 flc_p2
  ClearErrors
  FileOpen $R1 "$INSTDIR\python\pythonw.exe" a
  IfErrors flc_occupata
  FileClose $R1
  flc_p2:
  IfFileExists "$INSTDIR\python\python.exe" 0 flc_fine
  ClearErrors
  FileOpen $R1 "$INSTDIR\python\python.exe" a
  IfErrors flc_occupata
  FileClose $R1
  Goto flc_fine
  flc_occupata:
  StrCpy $R0 1
  flc_fine:
FunctionEnd
!macroend
!insertmacro FLC_IN_USO_FN ""
!insertmacro FLC_IN_USO_FN "un."

; finché FreeLaserCut è aperto chiede di chiuderlo; con «Annulla» esegue ABORT.
; Durante un aggiornamento dal programma prima aspetta fino a 30 secondi che FreeLaserCut finisca di chiudersi.
!macro FLC_ASPETTA_CHIUSO UN ABORT
  StrCpy $R2 0
  flc_riprova:
  Call ${UN}FlcInUso
  StrCmp $R0 1 0 flc_chiuso
  StrCmp $Aggiorna 1 0 flc_chiedi
  IntCmp $R2 60 flc_chiedi
  IntOp $R2 $R2 + 1
  Sleep 500
  Goto flc_riprova
  flc_chiedi:
  MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "FreeLaserCut è aperto (oppure un suo file è in uso).$\r$\n$\r$\nSalva il lavoro, chiudi FreeLaserCut e premi «Riprova»." /SD IDCANCEL IDRETRY flc_riprova
  ${ABORT}
  flc_chiuso:
!macroend

Function DirLeave
  ; niente "Programmi": senza permessi da amministratore non si può scrivere
  StrCmp "$INSTDIR" "$PROGRAMFILES64" flc_pf
  StrLen $1 "$PROGRAMFILES64\"
  StrCpy $2 "$INSTDIR" $1
  StrCmp $2 "$PROGRAMFILES64\" flc_pf
  StrCmp "$INSTDIR" "$PROGRAMFILES" flc_pf
  StrLen $1 "$PROGRAMFILES\"
  StrCpy $2 "$INSTDIR" $1
  StrCmp $2 "$PROGRAMFILES\" flc_pf
  Goto flc_scrivi
  flc_pf:
  MessageBox MB_ICONEXCLAMATION|MB_OK "Questa cartella è dentro «Programmi»: senza permessi da amministratore lì non si può scrivere.$\r$\n$\r$\nUsa la cartella proposta (AppData\Local\Programs\FreeLaserCut) o un'altra cartella del tuo profilo."
  Abort
  flc_scrivi:
  ; provo davvero a scrivere nella cartella scelta
  StrCpy $3 0
  IfFileExists "$INSTDIR\*.*" flc_esiste
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors flc_noperm
  StrCpy $3 1
  flc_esiste:
  ClearErrors
  FileOpen $0 "$INSTDIR\flc-prova-scrittura.tmp" w
  IfErrors flc_noperm
  FileClose $0
  Delete "$INSTDIR\flc-prova-scrittura.tmp"
  StrCmp $3 1 0 flc_inuso
  RMDir "$INSTDIR"
  Goto flc_inuso
  flc_noperm:
  StrCmp $3 1 0 +2
  RMDir "$INSTDIR"
  MessageBox MB_ICONEXCLAMATION|MB_OK "Non hai i permessi per scrivere in questa cartella:$\r$\n$INSTDIR$\r$\n$\r$\nScegline un'altra del tuo profilo, per esempio quella proposta."
  Abort
  flc_inuso:
  !insertmacro FLC_ASPETTA_CHIUSO "" "Abort"
FunctionEnd

Function .onInit
  StrCpy $Aggiorna 0
  ${GetParameters} $R9
  ClearErrors
  ${GetOptions} $R9 "/AGGIORNA" $R8
  IfErrors +2
  StrCpy $Aggiorna 1
FunctionEnd

; pagine di benvenuto, licenza, cartella e fine: già viste alla prima installazione
Function SaltaSeAggiorna
  StrCmp $Aggiorna 1 0 +2
  Abort
FunctionEnd

; aggiornamento riuscito: riapre FreeLaserCut (l'installatore gira come utente normale)
Function .onInstSuccess
  StrCmp $Aggiorna 1 0 +2
  Exec '"$INSTDIR\python\pythonw.exe" -m freelasercut'
FunctionEnd

Function un.onInit
  !insertmacro FLC_ASPETTA_CHIUSO "un." "Quit"
FunctionEnd

Section "FreeLaserCut" SecMain
  SectionIn RO
  StrCmp $Aggiorna 1 0 +2
  SetAutoClose true  ; aggiornamento: a fine installazione si chiude da solo e riapre FreeLaserCut
  ; aggiornamento: FreeLaserCut deve essere chiuso (potrebbe essere stato aperto dopo la scelta della cartella)
  !insertmacro FLC_ASPETTA_CHIUSO "" "Abort"
  ; tolgo il programma vecchio, i dati in %APPDATA%\FreeLaserCut restano
  flc_togli:
  RMDir /r "$INSTDIR\python.flc-prova"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\licenze-terze-parti"
  IfFileExists "$INSTDIR\python\*.*" flc_togli_ko
  IfFileExists "$INSTDIR\app\*.*" flc_togli_ko
  Goto flc_togli_ok
  flc_togli_ko:
  MessageBox MB_ICONSTOP|MB_RETRYCANCEL "Non riesco a togliere i file della versione precedente in:$\r$\n$INSTDIR$\r$\n$\r$\nDi solito succede perché FreeLaserCut è ancora aperto, oppure perché l'antivirus sta controllando i file. Chiudi FreeLaserCut, aspetta qualche secondo e premi «Riprova»." /SD IDCANCEL IDRETRY flc_togli
  Abort "Installazione annullata: i file della versione precedente sono in uso."
  flc_togli_ok:
  SetOutPath "$INSTDIR"
  File "stage\LICENSE"
  File "stage\README.md"
  File "stage\CHANGELOG.md"
  File "stage\LICENZE-TERZE-PARTI.md"
  File /r "stage\licenze-terze-parti"
  File /r "stage\python"
  File /r "stage\app"
  WriteUninstaller "$INSTDIR\Disinstalla FreeLaserCut.exe"

  ; prepara adesso, una volta sola, i file di Python (.pyc): senza, il primo avvio dopo l'installazione
  ; durava ~25 s invece di pochi secondi (provato su Windows 11). Un errore qui non blocca nulla.
  DetailPrint "Preparo FreeLaserCut per un avvio rapido (può volerci un minuto)…"
  nsExec::Exec '"$INSTDIR\python\python.exe" -X utf8 -m compileall -q -j 0 "$INSTDIR\app" "$INSTDIR\python\Lib"'
  Pop $0

  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-m freelasercut" "$INSTDIR\app\freelasercut\assets\logo.ico" 0 SW_SHOWNORMAL "" "Software libero di incisione laser"
  CreateShortcut "$SMPROGRAMS\${APP}\Disinstalla ${APP}.lnk" "$INSTDIR\Disinstalla FreeLaserCut.exe"
  ; avvio con la console visibile: se qualcosa va storto all'avvio, l'errore resta scritto nella finestra nera
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} (diagnostica).lnk" "$SYSDIR\cmd.exe" '/s /k ""$INSTDIR\python\python.exe" -X faulthandler -m freelasercut"' "$INSTDIR\app\freelasercut\assets\logo.ico" 0 SW_SHOWNORMAL "" "Avvia FreeLaserCut mostrando gli eventuali errori in una console"
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
  flc_togli:
  RMDir /r "$INSTDIR\python.flc-prova"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  IfFileExists "$INSTDIR\python\*.*" flc_togli_ko
  IfFileExists "$INSTDIR\app\*.*" flc_togli_ko
  Goto flc_togli_ok
  flc_togli_ko:
  MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "Alcuni file di FreeLaserCut non si possono togliere: forse il programma è ancora aperto, oppure l'antivirus li sta controllando.$\r$\n$\r$\nChiudi FreeLaserCut e premi «Riprova». Con «Annulla» la disinstallazione finisce lo stesso e puoi cancellare a mano la cartella:$\r$\n$INSTDIR" /SD IDCANCEL IDRETRY flc_togli
  DetailPrint "Restano dei file in $INSTDIR: si possono cancellare a mano."
  flc_togli_ok:
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
