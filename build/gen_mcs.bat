@echo off
setlocal
REM ===========================================================================
REM  gen_mcs.bat -- turn the .bit into a .mcs for Flash programming
REM  Needs: Vivado 2020.2.  Takes about 10-20 seconds.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set VIVADO=D:\Xilinx\Vivado\2020.2\bin\vivado.bat
cd /d %~dp0

if not exist "%VIVADO%" (
    echo [ERROR] Vivado not found: %VIVADO%
    pause
    exit /b 1
)

echo Generating .mcs from board_top.bit ...
"%VIVADO%" -mode batch -source gen_mcs.tcl -nojournal -nolog
echo.
echo done. (press any key to close)
pause >nul
