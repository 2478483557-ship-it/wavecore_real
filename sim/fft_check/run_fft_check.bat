@echo off
REM ===========================================================================
REM  run_fft_check.bat
REM  Regression for self_fft_1024 (three-peak criterion), 4 scenarios.
REM
REM  USAGE: double-click this file.
REM  PASS  : the log ends with "PASS=4 FAIL=0"
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM  cmd.exe reads .bat in the system codepage (GBK on Chinese Windows);
REM  UTF-8 Chinese text gets mis-decoded and breaks the script.
REM ===========================================================================
set XILINX_BIN=D:\Xilinx\Vivado\2020.2\bin
set PATH=%XILINX_BIN%;%PATH%
cd /d %~dp0

echo ==============================================================
echo   self_fft_1024 regression (4 scenarios)
echo ==============================================================
echo.

echo [1/3] compiling ...
call xvlog.bat --relax self_fft_1024.v twiddle_rom.v blk_mem_gen_1.v tb_self_fft.v
if errorlevel 1 goto err

echo.
echo [2/3] elaborating ...
call xelab.bat tb_self_fft -s tb_sim -timescale 1ns/1ps
if errorlevel 1 goto err

echo.
echo [3/3] simulating ...
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
