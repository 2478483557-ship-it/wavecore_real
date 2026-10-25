@echo off
REM One-click: sweep the lock-in SNR curve on the board.
REM Takes about 3 minutes. Result is printed; paste it into report/lockin_snr_curve.md
cd /d "%~dp0"

set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
if not exist "%PY%" goto nopy

set "PORT=%~1"
if "%PORT%"=="" set "PORT=COM5"

"%PY%" scan_lockin_snr.py %PORT%
goto end

:nopy
echo [ERROR] Python not found. Edit the PY path in this file.

:end
echo.
pause
