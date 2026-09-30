# WaveCore

**基于 FPGA 的多功能信号测量与频谱分析系统**
A multi-function signal measurement & spectrum analysis system based on FPGA.

> 全国大学生嵌入式芯片与系统设计竞赛 2026 · FPGA 创新设计赛道（AMD）· 自主选题（初级组）
> 状态更新：2026-09-30（全程：信号源/测量/FFT双峰/**自研FFT三峰**/波形上传/触发/**波形自动识别**/**扫频**全部上板验证 ✅；**已 Flash 固化**（断电自启）；串口 **460800**；协议 **v1.17**——`V=` 为 **4 位 mV** 且新增 **0x8C 电压标定**）

---

## 系统数据流（一条龙）

```
电脑(命令) ──串口下行──▶ FPGA
  ▲                          │
  │  DDS(NCO+正弦表) → 数字正弦 → DA(AD9708) → 模拟 → AD(AD9280) → 数字信号
  │                          │                 (DA→AD 回环 = 自测通道;
  │                          │                  外部信号也可直接从 AD 进)
  │                          ▼
  │              ┌─ 自动测量：频率(100Hz~1MHz<1%) + Vpp + 占空比/脉宽
  │              ├─ FFT 频谱：4096点@50kHz → Hann窗 → 主峰/第二峰
  │              ├─ 波形上传(0x83) + 触发采集(0x89)
  │              └─ 串口上行 ──▶ F=/S=/A= + D=/W= 行
  │                                   │
  └──────────────── PC 上位机 ◀───┘（F1 转发口保留，供 STM32 等外设选配）
```

## Features / 功能（均已上板验证 ✅）

| # | 功能 | 说明 | 验证数据 |
|---|------|------|---------|
| 1 | DDS 信号源 | 32bit NCO+正弦表；预设 100k/200k/500k/1M（按键/LED 档位）；**任意频率 0x85（1Hz~12.5MHz）**；**双音合成 0x87** | 37.5kHz 自测 F=0037500 |
| 2 | ADC 采集 | AD9280 采样(25M) + DA→AD 回环自测 | 回环 Vpp≈1039 mV（v1.17 起 `V=` 为 mV） |
| 3 | 自动测量 | 频率全频段 **100Hz~1MHz 误差<1%**（闸门/测周自动切换+迟滞+自适应阈值+**三层抗噪**）；Vpp 一键测量 | 100Hz±3、1k/5k/37.5k/100k/1M 精确 |
| 4 | FFT 频谱 | **4096 点 FFT** @50kHz 采样，Hann 加窗，双峰检测 | **1k+1.1k 双音分开：S=1001 + A=1099** |
| 5 | 串口协议 | 460800-8N1 双向(**v1.17**)；上行 F=/S=/A=/D=/W=/TY=/SF=/S2=/S3=；下行 0x81/0x83/0x85/0x87/0x88/0x89/0x8A/0x8B/0x8C（帧速查表 §6） | 全功能远程实测 ✅ |
| 6 | 波形上传(0x83) | 请求一次上传最近 **1024 点@50kHz**(20.5ms)波形；RAM 用 blk_mem_gen IP(官方姿势, SK-016) | PC 画出 1kHz 正弦 ✅ |
| 7 | 占空比 + 脉宽 | 计窗统计+施密特+5点中值+**3窗中值平滑**；由测量帧第二行输出 `D=/W=` | 方波1k/100k：49.9~50.4%、500us/6us ✅ |
| 8 | 波形整形(0x88) | 正弦/方波/三角 一键切换 | 方波全链路验证 ✅ |
| 9 | 触发采集(0x89) | 自由/上升沿/下降沿；帧首点=触发点 | B(上升)前6点全高 / C(下降)全低 ✅ |
| 10 | 资源与时序 | 大表全部 BRAM；**LUT 24.60% / FF 11.62% / BRAM 20.0% / DSP 30.0%**；**WNS +1.689ns** 全收敛（资源攻坚前 LUT 100.14% 超容） | 布局通过 ✅ |
| 11 | 自研FFT(对比) | 1024点 DIF，`0x8A` 按需运行回 **SF=/S2=/S3= 三峰行**；[资源对比表](report/resource_compare.md)：**502 LUT/7 DSP** vs IP 1771 LUT/9 DSP | 正弦 `976/0/0`、方波 `976/2978/4980`（bin20/61/102，逐字命中模型）✅ |
| 12 | **波形自动识别**(9/20) | 占比法识别 方波/正弦/三角；输出 `TY=` 行（含可信闸门）| ✅ 五场景全对（1k正弦/方波/三角 + 混叠/双音报3）|
| 13 | **扫频模式**(9/20) | `0x8B` 开关；1k→20k/100Hz步/50ms，循环 | ✅ 上板验证（瀑布图待上位机实现，见 backlog #2）|
| 14 | 未做(可选) | 音乐彩蛋(需先确认麦克风/资源)、高频多档fs、Spectrogram(上位机版) → `report/backlog.md`（权威状态板）| - |

## Hardware / 硬件平台

- 正点原子达芬奇 Pro（AMD Artix-7 XC7A35T）
- ATK_HS_AD_DA 模块（AD9708 DAC / AD9280 ADC）
- 人机交互：**PC 上位机（Python）**为主显示器（波形/仪表；Spectrogram 频谱瀑布**待实现**）
- ~~STM32F407 + 淘晶驰串口屏~~（9/20 决策取消；F1 转发口代码保留备用）；驻极体麦克风（彩蛋预留，未做）

## Environment / 开发环境

- Vivado **2020.2**；上板验证用 ILA + 串口助手；编码双轨见 SK-001（仓库 UTF-8 / 工程 GBK，转换脚本 `hw_analysis/to_gbk.py`）

## 怎么玩（快速上手 3 步）

1. 综合→生成比特流→Program Device（无 ILA 改动则流程固定；若综合报错先看 `skill/README.md` 技能包）
2. 串口助手 460800 打开，看到 `F=0100000Hz V=1039` 即活（v1.17 起 `V=` 是 **4 位毫伏(mV)**，不再是 LSB）
3. HEX 发命令玩功能（完整帧见协议文档）：
   - 切 1kHz：`5A A5 85 00 04 E8 03 00 00 74` → F≈1000、S≈1001、D≈050%
   - 切方波/三角：`5A A5 88 00 01 01 8A`（方波）/ `...02 8B`（三角）→ D≈50%、W≈半周期
   - 触发抓波：`5A A5 89 00 01 01 8B`（上升沿）→ `5A A5 83 00 01 00 84` → 波形从触发点开始
   - 扫频演示：`5A A5 8B 00 01 01 8D`（开始）/ `5A A5 8B 00 01 00 8C`（停止）→ 频率 1k→20k 循环
   - 自研FFT对照：`5A A5 8A 00 01 00 8B` → SF=/S2=/S3= 三行
   - 加 1.1kHz 开双音：`5A A5 87 00 04 4C 04 00 00 DB` → S=1001 + **A=1099**（双峰分辨！）
   - 电压标定(0x8C)：`5A A5 8C 00 04 40 1F 00 00 EF`（恢复默认 8000 = 7.8125 mV/LSB）/ `5A A5 8C 00 04 00 04 00 00 94`（原始 LSB 透传）→ `V=` 立即按新系数换算
   - 电压标定(0x8C)：`5A A5 8C 00 04 40 1F 00 00 EF`（恢复默认 8000 = 7.8125 mV/LSB）/ `5A A5 8C 00 04 00 04 00 00 94`（原始 LSB 透传）→ `V=` 立即按新系数换算

> 注意：FFT/波形观察窗 fs=50kHz（≤25kHz 才能看清波形/频谱，高频会混叠属正常）；双音下 F= 行会晃是拍频物理现象。

4. 拉波形画图（需 python）：`python host/wave_plot_example.py COM口`（自动发 0x83、解析并画图）

## 给队友：先读这些（按顺序）

1. **README.md**（本文件，总览）
2. **board/uart_protocol.md**（协议 **v1.17**：F=/S=/A=/D=/W=/TY=/SF=/S2=/S3= 行；0x81/0x83/0x85/0x87/0x88/0x89/0x8A/0x8B 命令；§6 帧速查表）
3. 你的任务书：队友1 → `report/teammate1_task.md`；队友2 → `report/teammate2_task.md`
4. **board/sample_serial_log.txt**（真实日志，离线练解析用）
5. 代码入口：上位机 → `host/serial_monitor_starter.py`（起步）；看波形 → `host/wave_plot_example.py`

> **实机须知**：板子已固化到 Flash，**插 USB 上电即出数据**（460800），无需 Vivado。测频率不受限；**看波形/频谱请设 ≤20kHz**（如 1kHz：HEX 发 `5A A5 85 00 04 E8 03 00 00 74`）。串口助手与 Python 不要同时占同一 COM 口。

## 分工与进度

- FPGA 已完成与待办清单、两位队友任务：见 `report/task_overview.md`
- **设计报告（全文初稿）：`report/design_report.md`**；提交清单：`report/submission_checklist.md`
- **全队 GitHub 协作规则（工位表/流程/小抄）**：见 `report/collab_guide.md`
- 里程碑：见 `report/progress_log.md`；获奖对标：`report/benchmark.md`；升级规划：`report/upgrade_plan.md`

## Directory Structure / 目录结构

```
wavecore/
├── README.md          # 项目简介 + 复现步骤（本文件）
├── src/               # 源码：board_top/dds_nco/sine_rom/dual_tone/freq_ctrl/da_send/ad_driver/freq_meter(三层抗噪)/measure_report/fft_demo/fft_report/hann_rom/wave_frame(触发)/uart_tx/uart_rx/cmd_decoder/bin2bcd/div_restore/uart_mirror(F1) …
├── sim/               # 仿真 testbench
├── build/             # 构建脚本(reset_and_build.tcl)
├── board/             # 上板：XDC、引脚表、串口协议 v1.17、实测记录、样例日志、flash_guide.md
├── host/              # 上位机(队友1 工位: serial_monitor_starter.py / wave_plot_example.py)
├── stm32/             # STM32+串口屏 资料归档（9/20 屏方案取消，F1 转发口保留）
├── skill/             # 技能包 SK-001~035（抗噪/触发/FFT四坑/固化/文档一致性等，含 Golden 案例）
└── report/            # 进度/任务书/协作须知/对标/升级/LLM记录/战报/自研FFT档案/backlog
```

## How to Reproduce / 复现步骤

1. Vivado 2020.2 打开 `D:/Verilog_project/wavecore/wavecore.xpr`（或 tcl 重建，见 `build/`）
2. Add Sources：`src/*.v`；IP：`xfft_0`(4096点FFT)、`blk_mem_gen_0`(1024×8 波形缓存)。`ila_0` 默认已移除(资源)；自研FFT(`self_fft_*`/`twiddle_rom`/`blk_mem_gen_1`)默认不加入（存档）
3. 约束用 `board/wavecore.xdc`（含 uart_rxd=E14）
4. 综合→实现→bitstream→Program Device；按"怎么玩"3 步验证

## License

MIT License, see [LICENSE](LICENSE).
