# 层次资源诊断：找出 LUT/FF 到底被谁吃掉
# 用法：vivado -mode batch -source diag_hier.tcl
set proj "D:/Verilog_project/wavecore/wavecore.xpr"
set out  "D:/Verilog_project/wavecore/diag_hier.rpt"

open_project $proj
open_run impl_1

report_utilization -hierarchical -hierarchical_depth 2 -file $out

puts "=== HIERARCHY ==="
set fh [open $out r]
set n 0
while {[gets $fh line] >= 0} {
    if {[string match "*|*" $line]} {
        if {[regexp {Slice LUTs|Slice Registers|Block RAM Tile|DSPs|CLB} $line]} {
            puts $line
            incr n
            if {$n > 40} break
        }
    }
}
close $fh
puts "=== END ==="
