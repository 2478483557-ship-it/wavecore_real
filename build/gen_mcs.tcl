# ============================================================================
#  gen_mcs.tcl -- 把 impl_1 的 board_top.bit 转成 Flash 固化用的 .mcs
#  用法: vivado -mode batch -source gen_mcs.tcl   (或双击 gen_mcs.bat)
# ============================================================================
set proj "D:/Verilog_project/wavecore"
set bit  "$proj/wavecore.runs/impl_1/board_top.bit"
set mcs  "$proj/wavecore.runs/impl_1/board_top.mcs"

if {![file exists $bit]} {
    puts "ERROR: .bit not found: $bit"
    exit 1
}

# mt25ql128 = 128Mbit = 16MB
write_cfgmem -force -format MCS -interface SPIx4 -size 16 \
    -loadbit "up 0x0 $bit" -file $mcs

puts "=========================================================="
puts " MCS written OK:"
puts "   $mcs"
puts " next: run program_flash.bat"
puts "=========================================================="
