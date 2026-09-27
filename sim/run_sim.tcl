#============================================================================
# run_sim.tcl —— 一键运行 tb_cmd_decoder 仿真 (Vivado 2020.2)
#
# 用法（在【已打开 wavecore 工程】的 Vivado Tcl Console 里执行）：
#     source sim/run_sim.tcl
#
# 它会：把 TB 加入 simulation sources（如未加）→ 设 top → 启动仿真 → run all
# 预期输出（Console 里）：
#     [TB] arb_load! fcw=85899 ...   [TB] sf_run 脉冲! ...
#     >>>>>> 自检通过 <<<<<<
#============================================================================

set sim_file "sim/tb_cmd_decoder.v"
if {![file exists $sim_file]} {
    # 兼容从别的目录 source 的情况：尝试相对脚本位置
    set sim_file [file join [file dirname [info script]] tb_cmd_decoder.v]
}
puts "== run_sim: using $sim_file"

# 1) 确保在工程上下文
if {[catch {current_project} p]} {
    puts "ERROR: 请先打开 wavecore 工程，再执行本脚本。"
    return
}
puts "== project: $p"

# 2) 加入 simulation sources（如未加）
set already [get_files -quiet *tb_cmd_decoder.v]
if {[llength $already] == 0} {
    puts "== adding $sim_file to sim_1"
    add_files -fileset sim_1 -norecurse $sim_file
} else {
    puts "== TB already in project"
}

# 3) 设 top 并启动
set_property top tb_cmd_decoder [get_filesets sim_1]
puts "== launching simulation ..."
launch_simulation

# 4) 跑完整流程（TB 里有 \$finish，会自动结束）
run all

puts "=========================================================="
puts "== DONE. 请在 Tcl Console 上方滚动查看 [TB] 打印；"
puts "== 波形窗口可添加 u_rx/cnt、u_rx/state、line 观察 108 拍。"
puts "=========================================================="
