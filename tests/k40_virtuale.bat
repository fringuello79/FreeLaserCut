@echo off
rem K40 virtuale per le prove (strumento di Ale): apre FreeLaserCut con una K40 finta e la finestrina del piano.
rem Doppio clic. Per andare 5 volte piu veloce: k40_virtuale.bat 5
rem Quello che succede va in tests\k40_virtuale-log.txt
cd /d "%~dp0.."
set "PYARG="
set "PY=%LOCALAPPDATA%\Programs\FreeLaserCut\python\python.exe"
if exist "%PY%" goto via
set "PY=%LOCALAPPDATA%\Programs\FreeLaserCut\python\pythonw.exe"
if exist "%PY%" goto via
set "PY=py"
set "PYARG=-3"
where py >nul 2>nul && goto via
set "PY=python"
set "PYARG="
:via
echo Avvio della K40 virtuale con: %PY% %PYARG%
"%PY%" %PYARG% tests\k40_virtuale.py %*
echo Uscita: %errorlevel%
if exist tests\k40_virtuale-log.txt type tests\k40_virtuale-log.txt
pause
