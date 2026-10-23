@echo off
rem ==========================================================================
rem  sync_to_d.bat  --  one-click: repo src/  ->  Vivado project src/
rem
rem  Repo keeps UTF-8 + LF (git norm). Vivado 2020.2 on a Chinese Windows
rem  needs GBK + CRLF, or the Chinese comments turn into garbage.
rem  This script converts and verifies; it never edits the repo copies.
rem
rem  Usage:  double-click  = compare only (safe, nothing written)
rem          sync_to_d.bat write   = actually sync, then rebuild is up to you
rem ==========================================================================
setlocal
cd /d "%~dp0.."

set "MODE="
if /i "%~1"=="write" set "MODE=--write"

echo.
echo ============================================================
echo  Source sync:  repo src\  --^>  Vivado src\
echo  Mode: %MODE%
echo ============================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY if exist "C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe" set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not defined PY if exist "C:\Users\Lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=C:\Users\Lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not defined PY (
    echo [ERROR] Python not found. Install Python 3 or edit the PY path above.
    pause
    exit /b 1
)

"%PY%" "tools\sync_to_d.py" %MODE% --with-host
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Done. If files were written, remember to rebuild:
    echo     D:\Verilog_project\wavecore\rebuild_bitstream.bat
) else (
    echo [ERROR] sync failed, see messages above.
)
echo.
pause
exit /b %RC%
