@echo off
REM ===========================================================================
REM  run_win.bat -- 0x90 window compare: noise floor must drop rect > Hann > Blackman
REM  USAGE : double-click,  or: run_win.bat COM5
REM  KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS
REM ===========================================================================
set PY=C:/Users/Lenovo/AppData/Local/Programs/Python/Python38/python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d %~dp0
if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    pause
    exit /b 1
)
"%PY%" lab_tools.py win %*
echo.
echo (press any key to close this window)
pause >nul
