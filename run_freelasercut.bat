@echo off
rem FreeLaserCut - (c) 2026 fringuello79 - GPL-3.0-or-later
setlocal
title FreeLaserCut
cd /d "%~dp0"

rem ---- ambiente gia pronto? avvio diretto
if exist ".venv\Scripts\pythonw.exe" goto deps

rem ---- cerco Python 3.10 o piu recente
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto venv
python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto venv

echo Python non e installato: lo installo adesso, serve una volta sola...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto venv
echo.
echo Non sono riuscito a installare Python da solo.
echo Scaricalo da python.org, spunta "Add python.exe to PATH" e riapri questo file.
start "" https://www.python.org/downloads/
pause
exit /b 1

:venv
echo Preparo FreeLaserCut: solo la prima volta, qualche minuto...
%PY% -m venv .venv
if errorlevel 1 goto fail

:deps
fc /b requirements.txt ".venv\installed.txt" >nul 2>nul
if not errorlevel 1 goto shortcut
echo Installo le librerie di FreeLaserCut...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto fail
copy /y requirements.txt ".venv\installed.txt" >nul

:shortcut
rem ---- primo avvio su un PC nuovo: porto calibrazione camera, profilo macchina e materiali
if exist "%~dp0dati_iniziali\" if not exist "%APPDATA%\FreeLaserCut\" if not exist "%APPDATA%\Freeburn\" xcopy "%~dp0dati_iniziali" "%APPDATA%\FreeLaserCut\" /E /I /Y >nul
if exist "%USERPROFILE%\Desktop\FreeLaserCut.lnk" goto run
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\FreeLaserCut.lnk'); $s.TargetPath='%~dp0run_freelasercut.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0freelasercut\assets\logo.ico'; $s.WindowStyle=7; $s.Save()" >nul 2>nul

:run
start "" ".venv\Scripts\pythonw.exe" -m freelasercut %*
exit /b 0

:fail
echo.
echo Qualcosa non ha funzionato durante la preparazione. Controlla la connessione a internet e riprova.
pause
exit /b 1
