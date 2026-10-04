@echo off
setlocal
REM ===========================================================================
REM  run_calibrate_ext.bat -- VOLTAGE CALIBRATION using an EXTERNAL SIGNAL SOURCE
REM
REM  *** DOUBLE-CLICK THIS .BAT FILE -- do NOT double-click the .py file! ***
REM
REM  !! THIS WINDOW IS INTERACTIVE: it will STOP AND ASK YOU for the value
REM     you set on the signal generator. Do NOT redirect its output. !!
REM
REM  Why this mode is better than the multimeter:
REM    the amplitude shown ON THE SIGNAL GENERATOR is the true value --
REM    no probe, no DC-offset confusion, no out-of-range clipping.
REM
REM  SETUP (do this BEFORE running):
REM    1) UNPLUG the DA->AD loopback wire from the AD input side
REM    2) Signal generator output --> AD module input
REM       Signal generator GND    --> board GND   (common ground REQUIRED)
REM    3) Waveform : SQUARE        (flat levels are easiest to read)
REM       Frequency: 1 kHz         (inside our 100Hz..1MHz spec)
REM       Amplitude: 1 Vpp         (safe; well inside the ADC range)
REM       DC offset: +1 V          (so the signal sits at 0.5..1.5 V)
REM    4) Confirm the screen reads Vpp (not Vrms / dBm)
REM
REM  What it does:
REM    - sends 0x8C 1024 (raw-LSB mode: serial V= becomes the raw ADC count)
REM    - reads that count, ASKS you for the generator's Vpp, computes KN = Vpp*1024/N
REM    - sends the new KN and reads back for verification
REM
REM  Only ONE program may hold the COM port: close run_gui.bat / the waterfall
REM  window / any serial assistant first.
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
cd /d %~dp0

if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    pause
    exit /b 1
)

echo ===============================================================
echo   Voltage calibration - EXTERNAL SIGNAL SOURCE mode
echo.
echo   Reminder: loopback wire unplugged from AD side?
echo             generator output -^> AD input, GND -^> GND?
echo             square wave, 1 kHz, 1 Vpp, +1 V offset?
echo ===============================================================
echo.

"%PY%" calibrate_helper.py %* --external
set RC=%ERRORLEVEL%

echo.
echo ===============================================================
echo   exit code = %RC%
echo ===============================================================
echo.
echo (press any key to close this window)
pause >nul
