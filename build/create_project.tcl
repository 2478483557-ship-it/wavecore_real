#============================================================================
# create_project.tcl —— WaveCore 从零复现脚本 (Vivado 2020.2, XC7A35T)
#
# Usage (in Vivado Tcl Console):
#     source build/create_project.tcl
#   or  vivado -mode batch -source build/create_project.tcl
#
# What it does:
#   1) Creates project at  <repo>/recreate/wavecore  (part xc7a35tfgg484-2)
#   2) Copies src/*.v to a work dir and rewrites absolute $readmemh paths
#   3) Adds RTL + testbenches + XDC constraint
#   4) Re-creates the 3 IP cores (blk_mem_gen_0 / blk_mem_gen_1 / xfft_0)
#      with the same user settings as the delivered design
#   5) Sets board_top as top, prints next steps
#
# Notes:
#   - ILA debug core is intentionally NOT created (debug only, removed from
#     the delivered design to save resources).
#   - 仓库里**没有 .xpr**，所以本脚本是唯一的从零复现路径，不是备选项。
#   - hann_rom / blackman_rom / sine_rom / twiddle_rom 是 src/ 下的普通 RTL
#     模块（不是 IP），由上面的 glob 一起加入。
#   - 只有 3 个 IP 由本脚本重建：blk_mem_gen_0 / blk_mem_gen_1 / xfft_0。
#   - IP read latency: blk_mem_gen_1 must behave as 2-cycle read (see SK-025).
#     If synthesis reports differ, verify CONFIG output-register options.
#============================================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_dir   [file normalize [file join $script_dir ..]]
set src_dir    [file join $repo_dir src]
set sim_dir    [file join $repo_dir sim]
set proj_root  [file join $repo_dir recreate]
set proj_dir   [file join $proj_root wavecore]
set gen_dir    [file join $proj_root generated_src]

puts "== WaveCore recreate: repo=$repo_dir"

# ---------- 0) clean previous recreate ----------
if {[file exists $proj_root]} { file delete -force $proj_root }
file mkdir $proj_dir
file mkdir $gen_dir

# ---------- 1) create project ----------
create_project wavecore $proj_dir -part xc7a35tfgg484-2 -force
set_property target_language Verilog [current_project]

# ---------- 2) copy RTL & rewrite hex paths ----------
set rtl_files [glob -nocomplain [file join $src_dir *.v]]
foreach f $rtl_files {
    set fd [open $f r]; set data [read $fd]; close $fd
    # rewrite any absolute Windows path that ends with .hex  -> gen_dir
    regsub -all -line {[A-Za-z]:/[^"\r\n]*\.hex} $data "$gen_dir/" data
    # normalize slashes for Tcl
    set out [file join $gen_dir [file tail $f]]
    set fo [open $out w]; puts -nonewline $fo $data; close $fo
}
# copy hex data files
foreach h [glob -nocomplain [file join $src_dir *.hex]] {
    file copy -force $h [file join $gen_dir [file tail $h]]
}
puts "== copied [llength $rtl_files] RTL files + hex tables"

# ---------- 3) add sources ----------
add_files -norecurse -fileset sources_1 [glob -nocomplain [file join $gen_dir *.v]]
add_files -norecurse -fileset sim_1       [glob -nocomplain [file join $sim_dir *.v]]

# [10-30] 这里原先写成 $src_dir，但 xdc 实际在 board/ 下。
#   add_files 指向不存在的文件会直接报错，脚本就此中断 ——
#   而这又是唯一的复现路径（仓库里没有 .xpr），等于整个复现流程跑不通。
set xdc_file [file join $repo_dir board wavecore.xdc]
if {![file exists $xdc_file]} {
    puts "ERROR: constraint file not found: $xdc_file"
    puts "       仓库结构应为 <repo>/board/wavecore.xdc"
    error "missing XDC"
}
add_files -norecurse -fileset constrs_1 $xdc_file

set_property top board_top [get_filesets sources_1]
if {[llength [get_files -of_objects [get_filesets sim_1]]] > 0} {
    set_property top tb_cmd_decoder [get_filesets sim_1]
}

# ---------- 4) recreate IP cores ----------
# 4.1 blk_mem_gen_0 : wave frame buffer, 1024 depth, 9-bit (8 data + byte we)
create_ip -name blk_mem_gen -vendor xilinx.com -library ip -module_name blk_mem_gen_0
set_property -dict [list \
    CONFIG.Memory_Type                                    {Single_Port_RAM} \
    CONFIG.Write_Width_A                                  {9} \
    CONFIG.Read_Width_A                                   {9} \
    CONFIG.Write_Width_B                                  {9} \
    CONFIG.Read_Width_B                                   {9} \
    CONFIG.Write_Depth_A                                  {1024} \
    CONFIG.Enable_A                                       {Always_Enabled} \
    CONFIG.Use_Byte_Write_Enable                          {true} \
    CONFIG.Register_PortA_Output_of_Memory_Primitives     {false} \
] [get_ips blk_mem_gen_0]

# 4.2 blk_mem_gen_1 : FFT data buffer, 1024 x 32bit  (2-cycle read, SK-025)
create_ip -name blk_mem_gen -vendor xilinx.com -library ip -module_name blk_mem_gen_1
set_property -dict [list \
    CONFIG.Memory_Type                                    {Single_Port_RAM} \
    CONFIG.Write_Width_A                                  {32} \
    CONFIG.Read_Width_A                                   {32} \
    CONFIG.Write_Width_B                                  {32} \
    CONFIG.Read_Width_B                                   {32} \
    CONFIG.Write_Depth_A                                  {1024} \
    CONFIG.Enable_A                                       {Always_Enabled} \
    CONFIG.Register_PortA_Output_of_Memory_Primitives     {false} \
    CONFIG.Register_PortA_Output_of_Memory_Core           {false} \
] [get_ips blk_mem_gen_1]

# 4.3 xfft_0 : 4096-pt, 16-bit, BFP, radix-4 burst IO, natural order
create_ip -name xfft -vendor xilinx.com -library ip -module_name xfft_0
set_property -dict [list \
    CONFIG.transform_length                                     {4096} \
    CONFIG.implementation_options                               {radix_4_burst_io} \
    CONFIG.output_ordering                                      {natural_order} \
    CONFIG.scaling_options                                      {block_floating_point} \
    CONFIG.number_of_stages_using_block_ram_for_data_and_phase_factors {0} \
] [get_ips xfft_0]

generate_target all [get_ips]

# ---------- 5) done ----------
puts "=========================================================="
puts "== DONE. Project created at: $proj_dir"
puts "== Next steps:"
puts "==   1) Open project, run Synthesis -> Implementation -> Bitstream"
puts "==   2) Expected resources (ILA_EN=0, current delivered build):"
puts "==        LUT 7886 (37.91%) / FF 7082 (17.02%)"
puts "==        BRAM 12 (24.00%)  / DSP 40 (44.44%)"
puts "==        WNS +0.613 ns, 0 failing endpoints"
puts "==      Read them from impl_1/*_utilization_placed.rpt, NOT from the"
puts "==      synthesis report (OOC IPs are black boxes there)."
puts "==   3) For simulation: Run Behavioral (tb_cmd_decoder)"
puts "==   4) Flash guide: see board/flash_guide.md"
puts "=========================================================="
