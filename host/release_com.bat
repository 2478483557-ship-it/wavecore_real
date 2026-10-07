@echo off
setlocal
REM ===========================================================================
REM  release_com.bat -- free the serial port WITHOUT rebooting
REM
REM  Symptom : "COM port occupied" / cannot open COMx after a script crashed
REM  Cause   : a leftover Python process still holds the serial handle
REM  Fix     : kill leftover Python processes  -->  port is freed instantly
REM
REM  NOTE: this kills ALL python.exe / pythonw.exe.
REM        Save your work in any other Python program first.
REM
REM  If it still fails after this, the board or the USB-serial chip may need
REM  a power-cycle: unplug the USB cable, wait 3 s, replug. Still no reboot.
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
echo Killing leftover Python processes that may hold the COM port...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python3.exe 2>nul
echo.
echo Done. Now try opening the COM port again.
echo.
echo (If it still says occupied: unplug and replug the USB cable.)
pause >nul
