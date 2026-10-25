@echo off
REM Live monitor for the lock-in sensor demo. Big numbers, updates while you move things.
REM Press S to snapshot, L to toggle lock-in, Q to quit.
cd /d "%~dp0"
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -u demo_lockin_monitor.py %~1
echo.
pause
goto :eof
:nopy
echo [ERROR] Python 3.8 not found at:
echo   %PY%
echo Edit the PY line in this file to point at your python.exe
pause
