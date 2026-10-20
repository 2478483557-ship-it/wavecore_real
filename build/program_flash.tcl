# ============================================================================
#  program_flash.tcl -- 把 .mcs 烧进板载 Flash（断电不丢）
#
#  [!] 会覆盖 Flash 里原有的固件。旧版本仍可用 program_device.bat 从 .bit 烧回 SRAM。
#  [!] GUI 里"Add 点不动"的坑：要先 Remove 已有配置存储器对象 —— 本脚本已自动处理。
#  用法: vivado -mode batch -source program_flash.tcl  (或双击 program_flash.bat)
# ============================================================================
set proj "D:/Verilog_project/wavecore"
set mcs  "$proj/wavecore.runs/impl_1/board_top.mcs"

if {![file exists $mcs]} {
    puts "ERROR: .mcs not found. Run gen_mcs.bat first."
    exit 1
}

open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target

set dev [lindex [get_hw_devices] 0]
puts "device: $dev"
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

# 若已存在配置存储器对象，先删掉（等价于 GUI 里的 Remove 后再 Add）
if {[llength [get_hw_cfgmems -quiet]] > 0} {
    puts "removing existing cfgmem object(s) first..."
    delete_hw_cfgmem [get_hw_cfgmems]
}

create_hw_cfgmem -hw_device $dev -mem_dev [lindex [get_cfgmem_parts {mt25ql128-spi-x1_x2_x4}] 0]
set cfg [get_property PROGRAM.HW_CFGMEM $dev]

set_property PROGRAM.BLANK_CHECK 0 $cfg
set_property PROGRAM.ERASE       1 $cfg
set_property PROGRAM.CFG_PROGRAM 1 $cfg
set_property PROGRAM.VERIFY      1 $cfg
set_property PROGRAM.CHECKSUM    0 $cfg
# [2026-10-20 修复] 下面三个参数原来漏了 —— 缺 ADDRESS_RANGE 会让
#   program_hw_cfgmem 报 "27-3347 Failure to set flash parameters"。
#   这三个是 board/flash_guide.md 里经过实测的那份 Tcl 才有的，
#   本脚本当初照抄时漏掉了，导致批量固化从来没成功过（只能走 GUI）。
set_property PROGRAM.ADDRESS_RANGE {use_file} $cfg
set_property PROGRAM.PRM_FILE {} $cfg
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} $cfg
set_property PROGRAM.FILES [list $mcs] $cfg

program_hw_cfgmem -hw_cfgmem $cfg

puts "=========================================================="
puts " FLASH PROGRAMMED OK"
puts " power-cycle the board and check that V= shows 5050"
puts "=========================================================="
close_hw_manager
