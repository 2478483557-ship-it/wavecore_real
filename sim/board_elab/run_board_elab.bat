@echo off
REM ===========================================================================
REM  run_board_elab.bat
REM  Full-top elaboration check (no Vivado GUI, no synthesis):
REM  copies all src\*.v + 4 IP behavior stubs, then xvlog + xelab on board_top.
REM  PASS = "Built simulation snapshot" near the end.
REM
REM  USAGE: double-click this file.
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat in the system codepage (GBK on Chinese Windows);
REM  UTF-8 Chinese text gets mis-decoded and breaks the script.
REM ===========================================================================
set XILINX_BIN=D:\Xilinx\Vivado\2020.2\bin
set PATH=%XILINX_BIN%;%PATH%
cd /d %~dp0

echo ==============================================================
echo   board_top elaboration check (port alignment, no synthesis)
echo ==============================================================
echo.

echo [1/3] copying sources and stubs ...
copy /Y ..\..\src\*.v . >nul
copy /Y ..\fft_check\blk_mem_gen_1.v . >nul
copy /Y ..\fft_demo_check\xfft_stub.v .\xfft_0.v >nul

echo [2/3] xvlog ...
call xvlog.bat --relax *.v
if errorlevel 1 goto err

echo.
echo [3/3] xelab ...
call xelab.bat board_top -s board_elab -timescale 1ns/1ps
if errorlevel 1 goto err

echo.
echo *** ELAB OK - all instantiations match ***
goto done

:err
echo.
echo *** FAILED - check the messages above (port name / width mismatch?) ***

:done
echo.
echo (press any key to close this window)
pause >nul
