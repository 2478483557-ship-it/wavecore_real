@echo off
setlocal
REM Step 2 of 3: sweep with the DUT in place.
REM DAC --[ DUT ]-- ADC
set PY=C://Users//Lenovo//AppData//Local//Programs//Python//Python38//python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d "%~dp0"
echo =============================================
echo   Step 2/3  sweep with the DUT in place
echo   DAC --[ DUT ]-- ADC
echo =============================================
echo.
"%PY%" bode_scan.py dut --name "first-order active LPF"
echo.
echo Done. Next: run run_bode_plot.bat
pause
