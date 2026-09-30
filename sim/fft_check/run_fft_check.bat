@echo off
REM ===========================================================================
REM  run_fft_check.bat
REM  Regression for self_fft_1024 (three-peak criterion).
REM  [2026-09-30] self_fft_1024 now instantiates hann_rom (Hann window root-cause
REM  fix for the false-peak bug), so hann_rom.v must be compiled too.
REM  hann_rom.v loads D:/Verilog_project/wavecore/src/hann_1024.hex by absolute
REM  path - keep that file in sync with ../../src/hann_1024.hex.
REM
REM  USAGE: double-click this file.
REM  PASS  : the log ends with "PASS=6 FAIL=0"
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat in the system codepage (GBK on Chinese Windows);
REM  UTF-8 Chinese text gets mis-decoded and breaks the script.
REM ===========================================================================
set XILINX_BIN=D:\Xilinx\Vivado\2020.2\bin
set PATH=%XILINX_BIN%;%PATH%
cd /d %~dp0

echo ==============================================================
echo   self_fft_1024 regression (6 scenarios)
echo ==============================================================
echo.

echo [1/4] copying DUT source from ..\..\src ...
copy /Y ..\..\src\self_fft_1024.v . >nul
copy /Y ..\..\src\hann_rom.v . >nul
if errorlevel 1 goto err

echo [2/4] compiling ...
call xvlog.bat --relax self_fft_1024.v hann_rom.v twiddle_rom.v blk_mem_gen_1.v tb_self_fft.v
if errorlevel 1 goto err

echo.
echo [3/4] elaborating ...
call xelab.bat tb_self_fft -s tb_sim -timescale 1ns/1ps
if errorlevel 1 goto err

echo.
echo [4/4] simulating ...
call xsim.bat tb_sim -R > xsim_run.log 2>&1
findstr /C:"PASS=" /C:"FAIL=" /C:"expect" xsim_run.log
echo.
echo   full log: %~dp0xsim_run.log
goto done

:err
echo.
echo *** compile or elaborate failed - see the messages above ***

:done
echo.
echo (press any key to close this window)
pause >nul
