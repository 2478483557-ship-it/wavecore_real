@echo off
REM ===========================================================================
REM  run_check_interp.bat -- one-click BOARD TEST for spectrum interpolation
REM
REM  Double-click this file. It will:
REM    1) send:  stop-sweep / 1000 Hz / square wave / run self-FFT (0x8A)
REM    2) read the board's text lines back and JUDGE them automatically:
REM         SF ~= 999  -> interpolation IS active   (old value was 976)
REM         SF ~= 976  -> interpolation NOT in this bitstream
REM
REM  Why:  the parabolic-interpolation feature moves the self-FFT reading from
REM        the raw bin value (976 Hz) to the interpolated one (~999 Hz) for a
REM        real 1000 Hz signal.  Threshold is clear: >=990 = new, <=988 = old.
REM
REM  Only ONE program may hold the COM port: close run_gui.bat / the waterfall
REM  window / any serial assistant first.
REM
REM  Extra options (type them after the .bat name, or edit this file):
REM     run_check_interp.bat COM5
REM     run_check_interp.bat COM5 --wave 0      (0=sine 1=square 2=triangle)
REM     run_check_interp.bat COM5 --secs 8
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe
cd /d %~dp0

if not exist "%PY%" (
    echo [ERROR] Python 3.8 not found: %PY%
    echo         edit run_check_interp.bat and fix the PY path.
    pause
    exit /b 1
)

"%PY%" check_interp.py %*
echo.
echo (press any key to close this window)
pause >nul
