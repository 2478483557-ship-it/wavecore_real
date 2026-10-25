@echo off
REM External sensor demo. Read the on-screen wiring checklist before starting.
cd /d "%~dp0"
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -u demo_sensor.py %~1
echo.
pause
goto :eof
:nopy
echo [ERROR] Python 3.8 not found at:
echo   %PY%
echo Edit the PY line in this file to point at your python.exe
pause
