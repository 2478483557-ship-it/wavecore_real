#=============================================================================
# rebuild_bitstream.tcl -- synthesis + implementation + bitstream, no GUI
#
# Why this exists: the Vivado 2020.2 GUI crashes with a TreeMap
# NullPointerException while restoring its log/report text boxes during
# open_project, which makes the project impossible to open. Batch mode has no
# such text boxes, so it never hits that bug.
#
# Usage: double-click rebuild_bitstream.bat   (recommended)
#        or: vivado -mode batch -source rebuild_bitstream.tcl
#
# Takes about 8-15 minutes.
#
# NOTE -- keep this file PURE ASCII. Vivado reads .tcl scripts using the
# system codepage (GBK on a Chinese Windows). A UTF-8 file with Chinese text
# gets mis-decoded and can break the script. Chinese documentation lives in
# board/README.md and the Chinese newbie guide in report/ instead.
#=============================================================================

set PROJ    "D:/Verilog_project/wavecore/wavecore.xpr"
set BITFILE "D:/Verilog_project/wavecore/wavecore.runs/impl_1/board_top.bit"

puts "=============================================================="
puts " Step 1 : opening project"
puts "          $PROJ"
puts "=============================================================="
if {[catch {open_project $PROJ} err]} {
    puts "ERROR: open_project failed: $err"
    exit 1
}
puts "PART = [get_property PART [current_project]]"

# Re-order the compile list so the edited sources are picked up.
puts "--------------------------------------------------------------"
puts " Step 2 : update_compile_order (picks up edited source files)"
puts "--------------------------------------------------------------"
update_compile_order -fileset sources_1

# Clear previous results but keep the sources.
puts "--------------------------------------------------------------"
puts " Step 3 : reset_run synth_1 / impl_1"
puts "--------------------------------------------------------------"
reset_run synth_1
reset_run impl_1

puts "--------------------------------------------------------------"
puts " Step 4 : launch_runs impl_1 -to_step write_bitstream -jobs 4"
puts "          (about 8-15 minutes, please wait)"
puts "--------------------------------------------------------------"
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

set st [get_property STATUS [get_runs impl_1]]
puts "--------------------------------------------------------------"
puts "impl_1 STATUS = $st"
puts "--------------------------------------------------------------"

if {[string match "*write_bitstream Complete*" $st]} {
    puts ""
    puts "=============================================================="
    puts " SUCCESS"
    if {[file exists $BITFILE]} {
        puts " bitstream : $BITFILE"
        puts " size      : [file size $BITFILE] bytes"
        puts " time      : [clock format [file mtime $BITFILE] -format {%Y-%m-%d %H:%M:%S}]"
    } else {
        puts " WARNING: status says Complete but the .bit file is missing!"
    }
    puts ""
    puts " NEXT: double-click check_lut.bat to verify resource usage,"
    puts "       then double-click program_device.bat to program the board."
    puts "=============================================================="
} else {
    puts ""
    puts "=============================================================="
    puts " FAILED : impl_1 did not reach write_bitstream Complete"
    puts " Look for the FIRST line starting with ERROR in:"
    puts "   D:/Verilog_project/wavecore/rebuild_bitstream.log"
    puts " If it says [DRC UTLZ-1] Slice LUTs over-utilized, the f_ram"
    puts " fix did not take effect -- run check_lut.bat and send the output."
    puts "=============================================================="
}

# Timing summary (numbers needed for the competition report).
if {[catch {
    open_run impl_1
    report_timing_summary -delay_type min_max -report_unconstrained \
        -check_timing_verbose -max_paths 10 \
        -file D:/Verilog_project/wavecore/timing_summary.rpt
    puts "timing summary written to D:/Verilog_project/wavecore/timing_summary.rpt"
} err2]} {
    puts "NOTE: could not write timing summary: $err2"
}

puts "=============================================================="
puts " Done. Full log: D:/Verilog_project/wavecore/rebuild_bitstream.log"
puts "=============================================================="
