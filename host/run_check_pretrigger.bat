@echo off
setlocal
REM ===========================================================================
REM  run_check_pretrigger.bat -- one-click BOARD TEST for 0x8F pre-trigger
REM
REM  *** DOUBLE-CLICK THIS .BAT FILE -- do NOT double-click the .py file! ***
REM      Double-clicking check_pretrigger.py closes its window instantly,
REM      because a bare Python script has no "pause" at the end.
REM
REM  What it does:
REM    1) send:  stop-sweep / 20 Hz square / rising-edge trigger
REM    2) for each pre-trigger level (0% / 25% / 50% / 75%):
REM         send 0x8F, request one waveform frame (0x83), count LOW samples
REM    3) print a PASS/FAIL table
REM
REM  Expected LOW-sample counts (20 Hz square: period = 2500 pts > 1024-pt frame):
REM      0%  ->     0     25% ->   256     50% ->   512     75% ->   768
REM
REM  Every run also writes the full output to  last_pretrigger.log (same folder).
REM  If the window ever disappears, just open that log file instead.
REM
REM  Only ONE program may hold the COM port: close run_gui.bat / the waterfall
REM  window / any serial assistant first.
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d %~dp0
set LOG=%~dp0last_pretrigger.log

if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    echo         edit run_check_pretrigger.bat and fix the PY path.
    pause
    exit /b 1
)

echo ===============================================================
echo   Pre-trigger 0x8F board test
echo   log file: %LOG%
echo ===============================================================
echo.

"%PY%" check_pretrigger.py %* > "%LOG%" 2>&1
set RC=%ERRORLEVEL%
type "%LOG%"

echo.
echo ===============================================================
echo   exit code = %RC%
echo   full log  = %LOG%
if not "%RC%"=="0" echo   [NOTE] non-zero exit -- send me the log file above.
echo ===============================================================
echo.
echo (press any key to close this window)
pause >nul
