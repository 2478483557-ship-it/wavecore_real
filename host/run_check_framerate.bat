@echo off
setlocal
REM ===========================================================================
REM  run_check_framerate.bat -- measure the REAL waveform frame rate
REM
REM  *** DOUBLE-CLICK THIS .BAT -- do NOT double-click the .py file! ***
REM
REM  Why: the waveform buffer is single-port RAM, so acquisition STOPS while
REM       a frame is being transmitted. That is a "dead time".
REM       This tool sends 0x83 back-to-back and counts complete frames/sec.
REM
REM  Reference: one frame = 1030 bytes @460800 8N1 ~= 22.4 ms
REM             --> theoretical upper bound ~= 44 frames/s
REM
REM  Before running: close run_gui.bat / waterfall / any serial assistant,
REM                  or only ONE program can hold the COM port.
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
echo   Waveform frame-rate test (dead-time measurement)
echo   Takes about 10 seconds. Please wait...
echo ===============================================================
echo.

"%PY%" check_framerate.py %*
set RC=%ERRORLEVEL%

echo.
echo ===============================================================
echo   exit code = %RC%
echo ===============================================================
echo.
echo (press any key to close this window)
pause >nul
