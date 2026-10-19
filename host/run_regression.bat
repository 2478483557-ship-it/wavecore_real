@echo off
REM ===========================================================================
REM  run_regression.bat
REM  Regression test for the 2026-10-19 implicit-declaration fix.
REM
REM  USAGE : just double-click this file.
REM  WHAT  : checks only the three paths I touched, not the whole system.
REM            freq_meter.v  -> F / V / D / TY
REM            board_top.v   -> neural-net path, 0x94 / 0x95 readback
REM            fft_demo.v    -> vendor IP FFT readings
REM
REM  !! KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat using the system codepage (GBK on Chinese Windows).
REM  UTF-8 Chinese gets mis-decoded into command separators and the script
REM  silently falls apart. Chinese notes live in the Python file's docstring.
REM ===========================================================================
setlocal
cd /d "%~dp0"

set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe

if not exist "%PY%" (
    echo.
    echo ERROR: Python 3.8 not found at
    echo   %PY%
    echo.
    echo This project needs the SYSTEM Python 3.8 because the managed 3.13
    echo does not have pyserial installed.
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   WaveCore regression - implicit declaration fix (2026-10-19)
echo ================================================================
echo.
echo   Before running, confirm on the board:
echo     1. Firmware burned AFTER 2026-10-19  (has F11 button in GUI)
echo     2. Loopback jumper connected (DAC out -> ADC in)
echo     3. Serial port 460800-8N1
echo.
echo   Close the GUI first - Windows allows only ONE process per COM port.
echo.
pause

echo.
"%PY%" regression_2026_10_19.py %*
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
    echo ================================================================
    echo   ALL PASS - the declaration fix did not change behaviour.
    echo ================================================================
) else (
    echo ================================================================
    echo   SOME CHECKS FAILED - see the list above, then read
    echo   the troubleshooting hints printed with it.
    echo ================================================================
)

echo.
pause
