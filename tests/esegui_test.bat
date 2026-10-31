@echo off
rem Esegue tutti i test di FreeLaserCut e salva il risultato in tests\ultimo_test.log
cd /d "%~dp0.."
title Test FreeLaserCut
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo Test di FreeLaserCut in corso (qualche minuto)...
".venv\Scripts\python.exe" tests\run_tests.py > tests\ultimo_test.log 2>&1
echo.
echo Fine. Il risultato e in tests\ultimo_test.log
timeout /t 5 >nul
