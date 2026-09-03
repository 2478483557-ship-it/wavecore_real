# ============================================================================
# reset_and_build.tcl
# 用途: 一键"重置所有运行 + 从零重新综合/实现/生成比特流"
# 为什么需要: 修改 ILA IP 后, Vivado 可能用旧的 OOC 缓存导致
#             烧进去的 ILA 探针数不对(只有 P0/P1 没有 P2)。
#             本脚本把所有 run 重置, 强制全新编译, 排除缓存问题。
# 使用方法(二选一):
#   A. 在已打开的 Vivado 工程里: Tcl Console 输入
#        source D:/Verilog_project/wavecore/reset_and_build.tcl
#   B. 命令行: vivado -mode batch -source D:/Verilog_project/wavecore/reset_and_build.tcl
# 注意: 脚本运行期间请勿操作界面; 跑完会打印 === BUILD FINISHED ===
# ============================================================================

# 打开工程(若已打开会提示, 忽略即可)
open_project D:/Verilog_project/wavecore/wavecore.xpr

# 1. 停掉并重置所有综合/实现 run(含 ILA 的 OOC run), 跳过仿真 run
foreach r [get_runs -quiet] {
    if {[string match "*sim*" $r]} { continue }
    catch { reset_run $r }
    puts "reset run: $r"
}

# 2. 从零综合(等它跑完)
puts ">>> Launching synthesis ..."
launch_runs synth_1 -jobs 4
wait_on_run synth_1
puts ">>> Synthesis status: [get_property STATUS [get_runs synth_1]]"

# 3. 从零实现并直接生成比特流(等它跑完)
puts ">>> Launching implementation + bitstream ..."
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
puts ">>> Implementation status: [get_property STATUS [get_runs impl_1]]"

puts "=== BUILD FINISHED ==="
puts "bitstream: D:/Verilog_project/wavecore/wavecore.runs/impl_1/board_top.bit"
