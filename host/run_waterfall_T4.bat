@echo off
REM ===========================================================================
REM  run_waterfall_T4.bat -- 0x8E spectrum viewer, preset: T4 = 200 kHz sample rate
REM                          (widest span: spectrum covers 0 .. 100 kHz)
REM
REM  Double-click this file. It will send:
REM    0x8B stop-sweep, 0x8D timebase=T4, 0x85 1000 Hz, 0x88 square,
REM    then request 0x8E spectrum frames and open the plot window.
REM
REM  Expect the SAME three lines at 1/3/5 kHz, but now at bins 5 / 15 / 26 (df=195.3 Hz)
REM  and the frequency axis runs 0 .. 100 kHz.
REM
REM  NOTE: whether the 50..100 kHz part is real signal or just the analog front-end
REM        roll-off is exactly what run_link_scan.bat measures. Do not read a
REM        "range extension" as "sensitivity" - the ADC is decimated 250:1 here.
REM
REM  Only ONE program may hold the COM port: close run_gui.bat / the waterfall
REM  window / any serial assistant first.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
call "%~dp0run_waterfall.bat" --sweep-stop --timebase 3 --freq 1000 --wave 1
