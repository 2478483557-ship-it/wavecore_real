@echo off
setlocal
REM Step 1 of 3: straight-through calibration.
REM Remove the DUT and connect DAC straight to ADC with a jumper wire.
set PY=C://Users//Lenovo//AppData//Local//Programs//Python//Python38//python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d "%~dp0"
echo =============================================
echo   Step 1/3  straight-through calibration
echo   DUT removed, DAC wired directly to ADC
echo =============================================
echo.
"%PY%" bode_scan.py thru --name "straight through"
echo.
echo Done. Next: insert the DUT, then run run_bode_dut.bat
pause
