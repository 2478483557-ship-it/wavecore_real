@echo off
REM ===========================================================================
REM  run_gui.bat -- start the WaveCore PC host GUI (tkinter + pyserial)
REM
REM  Why the Python path is hard-coded:
REM    This PC has several Python installs. The one that the plain "python"
REM    command resolves to does NOT have pyserial installed, so it fails with
REM    "ModuleNotFoundError: No module named 'serial'".
REM    Python 3.8 below is the one that has pyserial.
REM  Note: keep this file pure ASCII (Chinese in .bat gets garbled)
REM ===========================================================================
cd /d %~dp0

set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
if not exist "%PY%" goto nopy

echo Starting ... if no serial port shows up, click "refresh" and pick the COM port.
"%PY%" wavecore_gui.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo *** the program exited with an error, send me the text above ***
pause
exit /b 1

:nopy
echo [X] Python not found: %PY%
echo     Please run it from a command line instead:  python wavecore_gui.py
pause
exit /b 1
