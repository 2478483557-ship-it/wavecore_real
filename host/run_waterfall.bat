@echo off
REM ===========================================================================
REM  run_waterfall.bat -- WaveCore 0x8E spectrum / waterfall viewer (one-click)
REM
REM  USAGE : double-click            -> auto-pick the single COM port
REM          or: run_waterfall.bat COM5
REM
REM  Why the python path is hardcoded: this machine has two Pythons.
REM  Only the SYSTEM 3.8 has pyserial + matplotlib + numpy installed,
REM  so we must call it by absolute path (do NOT "fix" it back to python).
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d %~dp0

if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    echo         edit run_waterfall.bat and fix the PY path.
    pause
    exit /b 1
)

"%PY%" spectrum_waterfall.py %*
echo.
echo (press any key to close this window)
pause >nul
