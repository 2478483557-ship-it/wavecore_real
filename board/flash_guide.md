# 固件固化指南（Flash 烧录，2026-09-20 实测流程）

> 目标：断电重启后**无需 Vivado、无需 JTAG**，上电即运行最新设计
> 硬件：达芬奇Pro（XC7A35T + MT25QL128 SPI Flash）

> ⚠️ **先看这个**：如果 Vivado GUI 打不开工程 / `connect_hw_server` 连不上 / `vivado -mode batch` 卡住，
> 见 **`board/vivado_gui_troubleshoot.md`**（2026-09-30 的 GUI 崩溃排查手册 + 两条"不开 GUI"的脚本路线）。
> 只烧 SRAM（不固化 Flash）可以直接双击工程根目录的 **`program_device.bat`**，不需要打开工程。

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

## 三·五、批量脚本的两个内置 bug（2026-10-20 修复）

> 背景：`program_flash.bat` **从来没有成功跑通过**。之前的固化都是走 GUI（方式 A）。
> 所以脚本里的错误一直没被发现。批量固化若有问题，先对照下面两条。

| # | 位置 | 错在哪 | 现象 | 修法 |
|---|---|---|---|---|
| 1 | `gen_mcs.tcl` | 写的是 `-interface SPIx1`，但 XDC 里 `BITSTREAM.CONFIG.SPI_BUSWIDTH = 4`（本节上文也是 SPIx4） | `ERROR: [Writecfgmem 68-20] SPI_BUSWIDTH property is set to "4" ... has to be set to "1"` | 改成 `-interface SPIx4` |
| 2 | `program_flash.tcl` | 漏了 3 个 `PROGRAM.*` 参数 | `ERROR: [Labtools 27-3347] Failure to set flash parameters` | 补 `ADDRESS_RANGE {use_file}` / `PRM_FILE {}` / `UNUSED_PIN_TERMINATION {pull-none}` |

**核对方法**：`write_cfgmem` 的 interface 必须与 bit 里的 SPI_BUSWIDTH 一致；
`program_hw_cfgmem` 前把 `PROGRAM.*` 六个参数全部设齐（见方式 B 的清单）。

**⚠️ 仍未解决 —— 已排除清单（2026-10-20 22:00~22:35 实测）**

补完上述两处后，`program_hw_cfgmem` 依旧报 27-3347。逐项排除如下：

| 排除项 | 怎么排除的 | 结果 |
|---|---|---|
| 型号名 | 用 `get_cfgmem_parts -of_objects $dev` 取本器件支持的；再扫遍 8 个 128M/256M 型号 | 全失败 |
| JTAG 时钟太快 | `set_property PARAM.FREQUENCY` 依次 15M / 6M / 3M / 1.5M | 全失败 |
| 写入参数不全 | 9 个 `PROGRAM.*` 全部显式设置并回读确认 | 全失败 |
| 只是写入的问题 | 改成**只做 BLANK_CHECK**（纯读） | **也失败** |
| cfgmem 残留脏状态 | 杀干净 `hw_server`/`cs_server` 后全新会话 | 失败 |
| `refresh_hw_device` 干扰 | 跳过 refresh 直接建 cfgmem | 失败 |
| mcs 容量参数 | `-size` 单位是 **MBytes**，`16` = 16MB = 128Mbit，本来就对 | 不是问题 |
| FPGA 已配置状态 | 断电重启后立刻执行 | 失败 |

**关键推论**：错误发生在"设置 flash 参数"阶段，**还没开始读文件**。
连只读的 blank check 都过不去 → **不是文件、不是型号、不是参数，是 JTAG 到 Flash 这条链路本身没通。**

**下一步（按成功率排序）**：
1. **走 GUI（方式 A）** —— 文档记录 2026-09-20 用 GUI 成功过，这是唯一验证过的路径
2. 若 GUI 也失败：**上电时按住板上 PROG/RESET 键不放**，让 FPGA 保持未配置状态，
   此时 Flash 处于上电默认 SPI 模式，再执行固化
3. 仍失败：用示波器看 Flash 的 CS/CLK 上电后有没有活动

---


---

## 四、踩过的坑（按出现顺序）
| 现象 | 原因 | 解法 |
|---|---|---|
| Add Configuration Memory Device 灰 | ①目标被自动关闭 ②**器件上已有 cfgmem 节点** | `open_hw_target`；**右键已有节点 Remove 后再 Add** |
| PROGRAM.FILES 用 .bit 报错 | Flash 只认 .mcs/.bin | 先 write_cfgmem 生成 |
| "Failure to set flash parameters" | ①残留 cfgmem 脏 ②**脚本漏设置 3 个 PROGRAM 参数** ③FPGA 已配置时偶发 | 先 delete；对照 §三·五 补齐参数；仍失败则断电后立刻重试 |
| 错误后 target 自动关闭 | Vivado 行为 | 重新 open_hw_target 再继续 |
