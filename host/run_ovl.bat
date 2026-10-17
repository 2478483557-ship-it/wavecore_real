@echo off
REM ===========================================================================
REM  run_ovl.bat -- 0x91 frame overlap: spectrum grab time should roughly halve
REM  USAGE : double-click,  or: run_ovl.bat COM5
REM  KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS
REM ===========================================================================
set PY=C://Users//Lenovo//AppData//Local//Programs//Python//Python38//python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d %~dp0
if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    pause
    exit /b 1
)
"%PY%" lab_tools.py ovl %*
echo.
echo (press any key to close this window)
pause >nul
