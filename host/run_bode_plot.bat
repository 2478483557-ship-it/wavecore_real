@echo off
setlocal
REM Step 3 of 3: normalise against the through run and plot.
set PY=C://Users//Lenovo//AppData//Local//Programs//Python//Python38//python.exe
if not exist "%PY%" for /f "delims=" %%i in ('where python 2^>nul') do set PY=%%i
cd /d "%~dp0"
echo =============================================
echo   Step 3/3  normalise and plot
echo =============================================
echo.
"%PY%" bode_scan.py plot --name "first-order active LPF"
echo.
echo Figure written to bode_plot.png
pause
