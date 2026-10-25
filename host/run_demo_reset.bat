@echo off
REM Reset the board to a clean starting point before recording or demoing.
REM Turns off noise and lock-in, sets T1, sine, 1 kHz, auto source selection.
cd /d "%~dp0"
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -u demo_reset.py %~1
echo.
pause
goto :eof
:nopy
echo [ERROR] Python 3.8 not found at:
echo   %PY%
echo Edit the PY line in this file to point at your python.exe
pause
