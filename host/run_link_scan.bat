@echo off
REM ===========================================================================
REM  run_link_scan.bat -- analog chain frequency response (one-click)
REM
REM  Sweeps the DDS through the DA->AD loopback and records Vpp vs frequency:
REM      link_response.csv   frequency / Vpp median / spread / measured F / TY
REM      link_response.png   response curve
REM  The -3dB point = usable analog bandwidth -> decides which 0x8D tiers are safe.
REM  Needs the DA->AD loopback cable connected. Sweep is stopped inside the script.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d %~dp0
if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    pause
    exit /b 1
)
"%PY%" link_response_scan.py %*
echo.
echo (press any key to close this window)
pause >nul
