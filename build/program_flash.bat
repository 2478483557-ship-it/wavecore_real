@echo off
setlocal
REM ===========================================================================
REM  program_flash.bat -- write the .mcs into the board's SPI Flash
REM
REM  [!] This OVERWRITES the firmware currently stored in Flash.
REM      The old .bit can still be loaded to SRAM with program_device.bat.
REM  [!] Takes about 1-2 minutes (erase + program + verify).
REM  Run gen_mcs.bat FIRST if board_top.mcs does not exist.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
set VIVADO=D:\Xilinx\Vivado\2020.2\bin\vivado.bat
cd /d %~dp0

if not exist "%VIVADO%" (
    echo [ERROR] Vivado not found: %VIVADO%
    pause
    exit /b 1
)

echo Programming board Flash with board_top.mcs ...
echo (this takes 1-2 minutes, please wait)
"%VIVADO%" -mode batch -source program_flash.tcl -nojournal -nolog
echo.
echo done. POWER-CYCLE the board, then check V= shows 5050.
pause >nul
