#=============================================================================
# program_device.tcl -- program the FPGA, without opening the project
#
# Why this exists: the Vivado 2020.2 GUI crashes with a TreeMap
# NullPointerException while restoring its log/report text boxes during
# open_project. Programming the device does not need the project at all, so
# batch mode avoids the crash entirely and starts much faster.
#
# Usage: double-click program_device.bat   (recommended; it kills leftover
#        hw_server / cs_server processes first)
#        or: vivado -mode batch -source program_device.tcl
#
# ---------------------------------------------------------------------------
# How to verify after programming (UART 460800-8N1, send in THIS order):
#     5A A5 85 00 04 E8 03 00 00 74    set 1000 Hz     <<< must not be skipped
#     5A A5 88 00 01 00 89             waveform = sine
#     5A A5 8A 00 01 00 8B             run self-written FFT once
#   Expect: SF=0000976Hz / S2=0000000Hz / S3=0000000Hz
#   If S2 or S3 is not 0, the OLD firmware is still on the board.
#
#   Why "set 1000 Hz" cannot be skipped: after power-up/reset the default
#   preset is 100 kHz (freq_ctrl.v idx=0), while the self-written FFT samples
#   at only 50 kHz -> 100 kHz aliases and SF can never read 976.
#   Full checklist: board/verify_checklist.md
# ---------------------------------------------------------------------------
#
# NOTE -- keep this file PURE ASCII (Vivado reads .tcl in the system codepage,
# GBK on a Chinese Windows; UTF-8 Chinese breaks it). Chinese docs live in
# board/README.md and the Chinese newbie guide in report/.
#=============================================================================

set BITFILE "D:/Verilog_project/wavecore/wavecore.runs/impl_1/board_top.bit"

if {![file exists $BITFILE]} {
    puts "ERROR: bitstream not found: $BITFILE"
    puts "       Run rebuild_bitstream.bat first."
    exit 1
}
puts "BITFILE = $BITFILE"
puts "  time  = [clock format [file mtime $BITFILE] -format {%Y-%m-%d %H:%M:%S}]"
puts "  size  = [file size $BITFILE] bytes"

# ---- 1. open the hardware manager and connect to the local hw_server ----
puts "--------------------------------------------------------------"
puts " Step 1 : opening hardware manager"
puts "--------------------------------------------------------------"
open_hw_manager

if {[catch {connect_hw_server -url localhost:3121} err]} {
    puts "first connect failed: $err"
    puts "retrying with -allow_non_jtag ..."
    if {[catch {connect_hw_server -allow_non_jtag} err2]} {
        puts "ERROR: cannot reach hw_server: $err2"
        puts "  Things to try:"
        puts "   1) close every Vivado window"
        puts "   2) Task Manager -> end leftover hw_server.exe and cs_server.exe"
        puts "   3) move the USB cable to another port"
        puts "   4) reboot (releases ports 3121 / 3042)"
        exit 1
    }
}

# ---- 2. open the target and pick the first device ----
puts "--------------------------------------------------------------"
puts " Step 2 : opening hardware target"
puts "--------------------------------------------------------------"
if {[catch {open_hw_target} err]} {
    puts "ERROR: open_hw_target failed: $err"
    puts "  Board not connected? Check the USB cable, board power, FTDI driver."
    exit 1
}

set dev [lindex [get_hw_devices] 0]
if {$dev eq ""} {
    puts "ERROR: no device found in the target. Check board power and USB."
    exit 1
}
current_hw_device $dev
puts "DEVICE = $dev"
refresh_hw_device -update_hw_probes false $dev

# ---- 3. program ----
puts "--------------------------------------------------------------"
puts " Step 3 : programming"
puts "--------------------------------------------------------------"
set_property PROGRAM.FILE $BITFILE $dev
program_hw_devices $dev

puts ""
puts "=============================================================="
puts " DONE - the board is now running this bitstream (SRAM, lost on"
puts " power-off)."
puts " Next: run_gui.bat -> set 1000 Hz -> sine -> run FFT,"
puts "       expect SF=0000976 / S2=0000000 / S3=0000000"
puts "=============================================================="

close_hw_manager
