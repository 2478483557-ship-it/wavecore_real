@echo off
REM WaveCore weak-signal demo. Run this in front of the judges.
REM It walks through three steps and prints a conclusion table at the end.
cd /d "%~dp0"
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -u demo_weak_signal.py %~1
echo.
echo ---------------------------------------------------------------
echo  Demo finished. If the numbers above look wrong, check:
echo    1. the USB cable is on COM5 (or pass the port as an argument)
echo    2. nobody else is holding the port (close the GUI)
echo    3. the board is powered and the DDS loopback is connected
echo ---------------------------------------------------------------
pause
goto :eof
:nopy
echo [ERROR] Python 3.8 not found. Edit the PY path in this file.
pause
