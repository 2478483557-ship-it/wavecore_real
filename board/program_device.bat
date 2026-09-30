@echo off
REM ===========================================================================
REM  program_device.bat
REM  Program the FPGA with board_top.bit (no GUI, no project).
REM
REM  USAGE : just double-click this file.
REM  LOG   : program_device.log  -- full Vivado log
REM          program_steps.log  -- this script's own progress log
REM
REM  BEFORE RUNNING: board powered on, USB/JTAG cable plugged in, and no
REM  Vivado window open.
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat files using the system codepage (GBK on a Chinese
REM  Windows). UTF-8 Chinese text gets mis-decoded and breaks the script.
REM  Chinese docs: the Chinese newbie guide in report/
REM ===========================================================================
setlocal
cd /d "%~dp0"

set VIVADO_BIN=D:\Xilinx\Vivado\2020.2\bin
set STEPS=%~dp0program_steps.log
set BITFILE=%~dp0wavecore.runs\impl_1\board_top.bit

echo ================================================================ > "%STEPS%"
echo program_device.bat   started %DATE% %TIME% >> "%STEPS%"

echo.
echo ================================================================
echo   WaveCore : program the FPGA
echo ================================================================
echo.

echo [1/4] killing leftover hw_server / cs_server ...
taskkill /F /IM hw_server.exe >> "%STEPS%" 2>&1
taskkill /F /IM cs_server.exe >> "%STEPS%" 2>&1

echo [2/4] checking the bitstream file ...
if not exist "%BITFILE%" goto noBit
for %%B in ("%BITFILE%") do echo       board_top.bit : %%~tB  %%~zB bytes
echo [2/4] bitstream ok >> "%STEPS%"

if not exist "%VIVADO_BIN%\vivado.bat" goto noVivado

echo [3/4] programming (about 30-60 seconds) ...
echo [3/4] launching vivado.bat >> "%STEPS%"
call "%VIVADO_BIN%\vivado.bat" -mode batch -source program_device.tcl -log program_device.log -journal program_device.jou
echo [3/4] vivado.bat returned errorlevel %ERRORLEVEL% >> "%STEPS%"

echo.
echo [4/4] done.
echo       If it failed, open program_device.log and send me the LAST 20 LINES.
echo       Most common failure: cannot reach hw_server (ports 3121/3042 busy)
echo       -> Task Manager: end hw_server.exe / cs_server.exe, then retry.
goto done

:noBit
echo.
echo *** ERROR: no bitstream found ***
echo     %BITFILE%
echo     Run rebuild_bitstream.bat first.
echo [2/4] FAILED no bitstream >> "%STEPS%"
goto done

:noVivado
echo.
echo *** ERROR: Vivado not found at %VIVADO_BIN% ***
echo     Edit VIVADO_BIN near the top of this file if needed.
echo [2/4] FAILED vivado not found >> "%STEPS%"
goto done

:done
echo.
echo ----------------------------------------------------------------
echo  this script's log : %STEPS%
echo  vivado log        : %~dp0program_device.log
echo ----------------------------------------------------------------
echo.
echo (press any key to close this window)
pause >nul
