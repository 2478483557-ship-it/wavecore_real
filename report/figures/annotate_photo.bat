@echo off
REM Point-and-click annotation for the board photo.
REM Click the four locations in order, then press S to save.
cd /d "%~dp0"
set "PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -u annotate_photo.py
goto :eof
:nopy
echo [ERROR] Python 3.8 not found at:
echo   %PY%
echo.
echo Edit the PY line in this file to point at your python.exe
pause
