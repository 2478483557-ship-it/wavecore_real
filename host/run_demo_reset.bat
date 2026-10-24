@echo off
REM Reset the board to the demo starting point before recording.
cd /d %%~dp0
set PY=C:////Users////Lenovo////AppData////Local////Programs////Python////Python38////python.exe
if not exist "%%PY%%" goto nopy
"%%PY%%" -u demo_reset.py %%~1
echo.
pause
goto :eof
:nopy
echo [ERROR] Python 3.8 not found.
pause
