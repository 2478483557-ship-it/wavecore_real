# 固件固化指南（Flash 烧录，2026-09-20 实测流程）

> 目标：断电重启后**无需 Vivado、无需 JTAG**，上电即运行最新设计
> 硬件：达芬奇Pro（XC7A35T + MT25QL128 SPI Flash）

## 一、生成 .mcs（Tcl 或 GUI）
```tcl
write_cfgmem -format MCS -size 16 -interface SPIx4 \
  -loadbit {up 0x00000000 D:/Verilog_project/wavecore/wavecore.runs/impl_1/board_top.bit} \
  -force D:/Verilog_project/wavecore/wavecore.runs/impl_1/board_top.mcs
```
（`-size 16` = 128Mbit；也可用 GUI：Tools → Generate Memory Configuration File）

## 二、烧录到 Flash（两种方式）

### 方式 A：GUI（推荐，参数自动正确）
1. Hardware Manager → 打开目标 → **左键选中 xc7a35t_0**
2. ⚠️ **若器件下已有配置存储器节点（如 cfgmem_0），先右键它 → Remove**（否则 Add 是灰的！）
3. 右键器件 → **Add Configuration Memory Device** → 选 `mt25ql128-spi-x1_x2_x4` → OK
4. 右键新 Flash 节点 → **Program Configuration Memory Device** → 选 `.mcs` → 勾 Verify → Program

### 方式 B：Tcl（熟悉后一步到位）
```tcl
open_hw_target
current_hw_device [get_hw_devices xc7a35t_0]
# 如有残留先删（注意语法带 -hw_cfgmem）:
delete_hw_cfgmem -hw_cfgmem [get_hw_cfgmems]
create_hw_cfgmem -hw_device [current_hw_device] -mem_dev [lindex [get_cfgmem_parts {mt25ql128-spi-x1_x2_x4}] 0]
set_property PROGRAM.BLANK_CHECK  0 [current_hw_cfgmem]
set_property PROGRAM.ERASE        1 [current_hw_cfgmem]
set_property PROGRAM.CFG_PROGRAM  1 [current_hw_cfgmem]
set_property PROGRAM.VERIFY       1 [current_hw_cfgmem]
set_property PROGRAM.CHECKSUM     0 [current_hw_cfgmem]
set_property PROGRAM.ADDRESS_RANGE {use_file} [current_hw_cfgmem]
set_property PROGRAM.PRM_FILE {} [current_hw_cfgmem]
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} [current_hw_cfgmem]
set_property PROGRAM.FILES [list <你的.mcs绝对路径>] [current_hw_cfgmem]
program_hw_cfgmem -hw_cfgmem [current_hw_cfgmem]
```

## 三、上电验证
断电 → 重新上电 → XCOM(460800) → 应自动出 F/D/W/TY 行；发 `5A A5 8B 00 01 01 8D` 扫频可跑 = 固化成功

## 四、踩过的坑（按出现顺序）
| 现象 | 原因 | 解法 |
|---|---|---|
| Add Configuration Memory Device 灰 | ①目标被自动关闭 ②**器件上已有 cfgmem 节点** | `open_hw_target`；**右键已有节点 Remove 后再 Add** |
| PROGRAM.FILES 用 .bit 报错 | Flash 只认 .mcs/.bin | 先 write_cfgmem 生成 |
| "Failure to set flash parameters" | 残留 cfgmem 状态脏 | 按方式 A（GUI）或 B（先 delete）重来 |
| 错误后 target 自动关闭 | Vivado 行为 | 重新 open_hw_target 再继续 |
