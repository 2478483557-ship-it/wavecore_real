@echo off
REM ===========================================================================
REM  run_waterfall_grab.bat -- grab ONE spectrum frame to files (diagnostics)
REM
REM  Double-click this file. It will:
REM    1) send 0x85 (1000 Hz) + 0x88 (square) to the board,
REM    2) collect 200 spectrum frames (about 25 s, no window shown),
REM    3) write  last_shot.png  (what the plot looks like)
REM       and    last_frame.txt (the raw 512 amplitude codes of the last frame).
REM  Then tell the assistant -- it will read those two files and compare against
REM  the golden model (expected: bins 20 / 61 / 102, codes about 209 / 183 / 173).
REM
REM  !! KEEP THIS FILE PURE ASCII, WITH CRLF LINE ENDINGS !!
REM ===========================================================================
call "%~dp0run_waterfall.bat" --sweep-stop --freq 1000 --wave 1 --save "%~dp0last_shot.png" --dump "%~dp0last_frame.txt"
