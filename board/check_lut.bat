@echo off
REM ===========================================================================
REM  check_lut.bat -- check the synthesis utilization report
REM  Purpose : verify that "f_ram" really went into Block RAM
REM  Usage   : double-click AFTER rebuild_bitstream.bat has finished
REM  Note    : keep this file pure ASCII (Chinese text in .bat gets garbled
REM            because cmd.exe reads it in the GBK codepage)
REM  Note 2  : every line is deliberately kept OUT of a ( ) block, so a
REM            codepage accident can never break the parenthesis nesting.
REM
REM  HISTORY : the first version of this file printed WRONG expected values.
REM            It said "RAMB18 4 -> 6" -- that criterion is bogus, because the
REM            synthesis report EXCLUDES the out-of-context IPs (xfft_0,
REM            blk_mem_gen_0/1 appear as Black Boxes), so the block RAM count
REM            is under-reported at synthesis time. f_ram actually lands as
REM            ONE RAMB36E1 (4096 x 8 = 32 Kb fits a 36 Kb block).
REM            Verified-good values are now baked in below (2026-09-30).
REM ===========================================================================
set RPT=D:\Verilog_project\wavecore\wavecore.runs\synth_1\board_top_utilization_synth.rpt
set BIT=D:\Verilog_project\wavecore\wavecore.runs\impl_1\board_top.bit

echo.
echo ================================================================
echo   WaveCore resource check  (synthesis report)
echo ================================================================
echo.

if not exist "%RPT%" goto noreport

for %%A in ("%RPT%") do echo   Report time : %%~tA
echo   Report path : %RPT%
echo.
echo   ---------- ACTUAL  (these lines come straight from the report) ----
echo.
findstr /C:"Slice LUTs" /C:"Slice Registers" /C:"F7 Muxes" /C:"F8 Muxes" /C:"RAMB18E1 |" /C:"RAMB36E1 |" "%RPT%"
echo.
echo   ---------- EXPECTED  (known-good, verified 2026-09-30) -----------
echo.
echo     Slice LUTs         about 3700          (was 19231)
echo     Slice Registers    about 2500          (was 35818)  *** KEY ***
echo                        still 30000+ means the f_ram fix did NOT work
echo     F7 / F8 Muxes      11 / 4              (was 4379 / 2180)
echo     RAMB36E1           1                   (this ONE is f_ram itself)
echo.
echo   NOTE: the synthesis report does NOT include the out-of-context IPs
echo   (xfft_0 / blk_mem_gen_0 / blk_mem_gen_1 show up as "Black Boxes"),
echo   so its totals are SMALLER than the real design. That is normal.
echo   Do NOT use the RAMB18 column as a pass/fail criterion.
echo.
echo   ---------- REAL design usage  (after place_design) --------------
echo.
echo     Slice LUTs      5117 (24.6 pct)      was 20829 (100.1 pct, OVER)
echo     Slice Registers 4834 (11.6 pct)      was 35818 ( 86.1 pct)
echo     -^> see impl_1\board_top_utilization_placed.rpt
echo.
echo   IMPORTANT: if the "Report time" above is not from just now,
echo   synthesis did NOT re-run and every number above is stale.
echo.
echo   ---------- BITSTREAM  (did implementation finish?) ---------------
echo.
if exist "%BIT%" goto bitok
echo     board_top.bit : NOT FOUND
echo.
echo     Implementation did not finish. Open this file and look for ERROR:
echo         wavecore.runs\impl_1\runme.log
echo     (most likely UTLZ-1 again -- send me the numbers above)
echo.
goto bitdone
:bitok
for %%B in ("%BIT%") do echo     board_top.bit : %%~tB   %%~zB bytes
echo.
echo     Size should be about 2190000 bytes, and this time must be
echo     LATER than the report time shown at the top.
echo.
:bitdone
echo ================================================================
echo   Copy or screenshot the lines above and send them to me.
echo ================================================================
echo.
pause
exit /b 0

:noreport
echo   [X] Report file not found:
echo       %RPT%
echo.
echo   This means synthesis has not run yet.
echo   Please double-click rebuild_bitstream.bat first.
echo.
pause
exit /b 1
