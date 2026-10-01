@echo off
REM ===========================================================================
REM  run_waterfall_T3.bat -- 0x8E spectrum viewer, preset: T3 = 100 kHz sample rate (wide span)
REM
REM  Double-click this file. It will send:
REM    0x8B stop-sweep, 0x8D timebase, 0x85 1000 Hz, 0x88 square,
REM    then request 0x8E spectrum frames and open the plot window.
REM  Expect the SAME three lines at 1/3/5 kHz, but now at bins 10 / 31 / 51 (df=97.7Hz).
REM
REM  Close the plot window to exit. Only ONE program may hold the COM port.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
call "%~dp0run_waterfall.bat" --sweep-stop --timebase 2 --freq 1000 --wave 1
