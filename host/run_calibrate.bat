@echo off
setlocal
REM ===========================================================================
REM  run_calibrate.bat -- one-click VOLTAGE CALIBRATION helper (0x8C)
REM
REM  *** DOUBLE-CLICK THIS .BAT FILE -- do NOT double-click the .py file! ***
REM
REM  !! THIS WINDOW IS INTERACTIVE: it will STOP AND ASK YOU for the
REM     multimeter readings. Do NOT redirect its output to a file --
REM     the questions would then be invisible. !!
REM
REM  It will automatically:
REM    1) send 0x8C 1024  -> raw-LSB mode (serial V= becomes the raw ADC count)
REM    2) send 0x88 01    -> square wave (easiest to measure with a multimeter)
REM    3) send 0x85 1Hz   -> 1 Hz, so HIGH and LOW each last 0.5 s
REM    4) then ASK you for the multimeter readings, compute KN, and send it
REM
REM  Multimeter setup (once):
REM    Mode : DC voltage (V with a straight/dashed line), 2 V or 20 V range
REM    Red  : DA output / AD input (either end of the loopback wire)
REM    Black: GND
REM
REM  Only ONE program may hold the COM port: close run_gui.bat / the waterfall
REM  window / any serial assistant first.
REM
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

echo ===============================================================
echo   Voltage calibration helper (0x8C)
echo.
echo   This window will PAUSE and ASK you for the multimeter
echo   readings. Just type the numbers and press Enter.
echo ===============================================================
echo.

"%PY%" calibrate_helper.py %*
set RC=%ERRORLEVEL%

echo.
echo ===============================================================
echo   exit code = %RC%
echo ===============================================================
echo.
echo (press any key to close this window)
pause >nul
