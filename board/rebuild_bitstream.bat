@echo off
REM ===========================================================================
REM  rebuild_bitstream.bat
REM  Command line synthesis + implementation + bitstream (no GUI).
REM
REM  USAGE : just double-click this file.
REM  OUTPUT: rebuild_bitstream.log  -- full Vivado log
REM          rebuild_steps.log     -- this script's own progress log
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat files using the system codepage (GBK on a Chinese
REM  Windows). UTF-8 Chinese text gets mis-decoded into characters that cmd
REM  treats as command separators, so the script silently falls apart.
REM  This file used to be UTF-8 with Chinese and it NEVER actually started
REM  Vivado. Keep it ASCII. Chinese docs: the Chinese newbie guide in report/
REM ===========================================================================
setlocal
cd /d "%~dp0"

set VIVADO_BIN=D:\Xilinx\Vivado\2020.2\bin
set STEPS=%~dp0rebuild_steps.log

echo ================================================================ > "%STEPS%"
echo rebuild_bitstream.bat   started %DATE% %TIME% >> "%STEPS%"
echo working dir: %CD% >> "%STEPS%"

echo.
echo ================================================================
echo   WaveCore : rebuild bitstream (synthesis + implementation)
echo.
echo   Takes about 8-15 minutes. Do NOT close this window.
echo   Text may scroll fast - that is normal.
echo ================================================================
echo.

echo [1/5] killing leftover hw_server / cs_server ...
taskkill /F /IM hw_server.exe >> "%STEPS%" 2>&1
taskkill /F /IM cs_server.exe >> "%STEPS%" 2>&1

echo [2/5] checking Vivado installation ...
if not exist "%VIVADO_BIN%\vivado.bat" goto noVivado
echo       found %VIVADO_BIN%\vivado.bat
echo [2/5] ok, vivado found >> "%STEPS%"

echo [3/5] running Vivado (this is the long part) ...
echo [3/5] launching vivado.bat >> "%STEPS%"
call "%VIVADO_BIN%\vivado.bat" -mode batch -source rebuild_bitstream.tcl -log rebuild_bitstream.log -journal rebuild_bitstream.jou
set RC=%ERRORLEVEL%
echo [3/5] vivado.bat returned errorlevel %RC% >> "%STEPS%"

echo.
echo [4/5] checking the result ...
if exist "%~dp0wavecore.runs\impl_1\board_top.bit" goto gotBit

echo *** board_top.bit was NOT created. ***
echo     The build did not finish. Open rebuild_bitstream.log and look
echo     for the FIRST line that starts with ERROR.
echo [4/5] FAILED : no bitstream >> "%STEPS%"
goto done

:gotBit
for %%B in ("%~dp0wavecore.runs\impl_1\board_top.bit") do echo     OK : board_top.bit  %%~tB  %%~zB bytes
for %%B in ("%~dp0wavecore.runs\impl_1\board_top.bit") do echo [4/5] OK bitstream %%~tB %%~zB bytes >> "%STEPS%"
echo.
echo [5/5] ALL GOOD. Next: double-click program_device.bat to program the board.
goto done

:noVivado
echo.
echo *** ERROR: Vivado not found at %VIVADO_BIN% ***
echo     If Vivado is installed somewhere else, edit the VIVADO_BIN
echo     path near the top of this file.
echo [2/5] FAILED vivado not found >> "%STEPS%"
goto done

:done
echo.
echo ----------------------------------------------------------------
echo  this script's log : %STEPS%
echo  vivado log        : %~dp0rebuild_bitstream.log
echo ----------------------------------------------------------------
echo.
echo (press any key to close this window)
pause >nul
