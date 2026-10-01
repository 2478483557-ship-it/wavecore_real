@echo off
REM ===========================================================================
REM  run_waterfall_sweep.bat -- 0x8E spectrum / waterfall viewer, preset: sweep demo (1kHz square + sweep on)
REM
REM  Double-click this file. It will:
REM    1) send the setting frames to the board (--freq 1000 --wave 1 --sweep),
REM    2) then request 0x8E spectrum frames and open the plot window.
REM  Expect a DIAGONAL line in the waterfall (the sweep).
REM
REM  Close the plot window to exit.  Only ONE program may hold the COM port,
REM  so close run_gui.bat / any serial assistant / other copies of this first.
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
call "%~dp0run_waterfall.bat" --freq 1000 --wave 1 --sweep
