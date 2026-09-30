@echo off
REM ===========================================================================
REM  run_equiv.bat -- fft_demo equivalence regression (Vivado 2020.2 XSim)
REM
REM  Why run it : we moved "f_ram" out of 32768 flip-flops into real Block RAM.
REM               This proves the sample stream fed to the FFT is byte-identical.
REM  How to read: if the last block says PASS, you are done.
REM  Usage      : double-click. If nothing happens for 2 minutes, press Ctrl+C
REM               and tell me.
REM  Note       : keep this file pure ASCII (Chinese in .bat gets garbled)
REM ===========================================================================
set XILINX_BIN=D:\Xilinx\Vivado\2020.2\bin
set PATH=%XILINX_BIN%;%PATH%
cd /d %~dp0

echo [0/4] syncing sources from the repo ...
copy /Y ..\..\src\fft_demo.v fft_demo_new.v >nul
copy /Y ..\..\src\hann_rom.v  hann_rom.v     >nul

echo.
echo ====== [1/4] OLD version (f_ram = flip-flops) ======
if exist xsim.dir rmdir /S /Q xsim.dir
call xvlog.bat --relax fft_demo_old.v hann_rom.v xfft_stub.v tb_fft_demo.v
if errorlevel 1 goto err
call xelab.bat tb_fft_demo -s sim_old -timescale 1ns/1ps
if errorlevel 1 goto err
call xsim.bat sim_old -R > out_old_raw.txt 2>&1
findstr /C:"[STUB]" /C:"[TB]" out_old_raw.txt > out_old.txt
type out_old.txt

echo.
echo ====== [2/4] NEW version (f_ram = Block RAM) ======
if exist xsim.dir rmdir /S /Q xsim.dir
call xvlog.bat --relax fft_demo_new.v hann_rom.v xfft_stub.v tb_fft_demo.v
if errorlevel 1 goto err
call xelab.bat tb_fft_demo -s sim_new -timescale 1ns/1ps
if errorlevel 1 goto err
call xsim.bat sim_new -R > out_new_raw.txt 2>&1
findstr /C:"[STUB]" /C:"[TB]" out_new_raw.txt > out_new.txt
type out_new.txt

echo.
echo ====== [3/4] comparing line by line ======
fc /N out_old.txt out_new.txt > diff_out.txt 2>&1
if errorlevel 1 goto diffbad
echo.
echo ================================================================
echo   PASS: both versions produce an identical sample stream.
echo         The change did NOT alter behaviour.
echo ================================================================
goto done

:diffbad
echo.
echo ================================================================
echo   FAIL: the two versions differ. Details below (send this to me)
echo ================================================================
type diff_out.txt
goto done

:err
echo.
echo *** compile or elaborate failed, see the messages above ***

:done
echo.
echo Logs: out_old_raw.txt / out_new_raw.txt / diff_out.txt
pause
