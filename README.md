# WaveCore

**基于 FPGA 的多功能信号测量与频谱分析系统**
A multi-function signal measurement & spectrum analysis system based on FPGA.

> 全国大学生嵌入式芯片与系统设计竞赛 2026 · FPGA 创新设计赛道（AMD）· 自主选题（初级组）
> 状态更新：2026-09-05（信号源/自动测量/4096点FFT双峰分辨/串口协议 已全部上板验证 ✅）

---

## 系统数据流（一条龙）

```
电脑(命令) ──串口下行──▶ FPGA
  ▲                          │
  │  DDS(NCO+正弦表) → 数字正弦 → DA(AD9708) → 模拟 → AD(AD9280) → 数字信号
  │                          │                 (DA→AD 回环 = 自测通道;
  │                          │                  外部信号也可直接从 AD 进)
  │                          ▼
  │              ┌─ 自动测量：频率(100Hz~1MHz<1%) + Vpp
  │              ├─ FFT 频谱：4096点@50kHz → Hann窗 → 主峰/第二峰
  │              └─ 串口上行 ──▶ F=/S=/A= 行
  │                                   │
  └──────────────── 上位机/串口屏 ◀───┘
```

## Features / 功能（均已上板验证 ✅）

| # | 功能 | 说明 | 验证数据 |
|---|------|------|---------|
| 1 | DDS 信号源 | 32bit NCO+正弦表；预设 100k/200k/500k/1M（按键/LED 档位）；**任意频率 0x85（1Hz~12.5MHz）**；**双音合成 0x87** | 37.5kHz 自测 F=0037500 |
| 2 | ADC 采集 | AD9280 采样(25M) + DA→AD 回环自测 | 回环 Vpp≈133 |
| 3 | 自动测量 | 频率全频段 **100Hz~1MHz 误差<1%**（闸门/测周自动切换+迟滞+自适应阈值）；Vpp 一键测量 | 100Hz±3、1k/5k/37.5k/100k/1M 精确 |
| 4 | FFT 频谱 | **4096 点 FFT** @50kHz 采样，Hann 加窗，双峰检测 | **1k+1.1k 双音分开：S=1001 + A=1099** |
| 5 | 串口协议 | 115200-8N1 双向；上行 F=/S=/A=；下行 0x81 切档/0x85 任意频/0x87 双音（带校验和，帧见 `board/uart_protocol.md`） | 电脑远程切频实测 ✅ |
| 6 | 资源优化 | 大缓存/大表全部 BRAM 化 | Utilization: **LUT 19282/20800, BRAM 7/50** |
| 7 | 未做(彩蛋/波形帧) | 音乐频谱彩蛋(XADC)、波形/幅度谱帧上传、自研 FFT 对比 → 见 `report/task_overview.md` | - |

## Hardware / 硬件平台

- 正点原子达芬奇 Pro（AMD Artix-7 XC7A35T）
- ATK_HS_AD_DA 模块（AD9708 DAC / AD9280 ADC）
- STM32F407（人机交互，转发数据到串口屏——队友2 分工）
- 淘晶驰串口屏（板载显示）；驻极体麦克风（彩蛋，预留 XADC）

## Environment / 开发环境

- Vivado **2020.2**；上板验证用 ILA + 串口助手；编码双轨见 SK-001（仓库 UTF-8 / 工程 GBK，转换脚本 `hw_analysis/to_gbk.py`）

## 怎么玩（快速上手 3 步）

1. 综合→生成比特流→Program Device（无 ILA 改动则流程固定；若综合报错先看 `skill/README.md` 技能包）
2. 串口助手 115200 打开，看到 `F=0100000Hz V=133` 即活
3. HEX 发命令玩功能（完整帧见协议文档）：
   - 切 1kHz：`5A A5 85 00 04 E8 03 00 00 74` → F≈1000、S≈1001
   - 加 1.1kHz 开双音：`5A A5 87 00 04 4C 04 00 00 DB` → S=1001 + **A=1099**（双峰分辨！）

> 注意：FFT 当前观察窗 fs=50kHz（只覆盖 ≤25kHz，100k+ 会被混叠到直流，属正常）；高频谱多档采样率在待办。双音下 F= 行会晃是拍频物理现象。

## 分工与进度

- FPGA 已完成与待办清单、两位队友任务：见 `report/task_overview.md`
- 里程碑：见 `report/progress_log.md`；获奖对标：`report/benchmark.md`；升级规划：`report/upgrade_plan.md`

## Directory Structure / 目录结构

```
wavecore/
├── README.md          # 项目简介 + 复现步骤（本文件）
├── src/               # 设计源码(RTL)：board_top/dds/da/ad/freq_meter/fft_demo/fft_report/cmd_decoder/dual_tone/uart/bin2bcd/hann_rom(+hex)…
├── sim/               # 仿真 testbench
├── build/             # 构建脚本(reset_and_build.tcl)
├── board/             # 上板：XDC、引脚表、串口协议、实测记录、样例日志
├── host/              # 上位机起步代码(队友1: serial_monitor_starter.py)
├── skill/             # 技能包 SK-001~015（踩坑清单）
└── report/            # 进度/任务书/FFT设计/对标/升级/LLM协作记录
```

## How to Reproduce / 复现步骤

1. Vivado 2020.2 打开 `D:/Verilog_project/wavecore/wavecore.xpr`（或 tcl 重建，见 `build/`）
2. Add Sources：`src/*.v` + IP：`xfft_0`(FFT 9.1, 4096点, Radix-4 Burst/BFP)、`ila_0`(3×8bit 探针)
3. 约束用 `board/wavecore.xdc`（含 uart_rxd=E14）
4. 综合→实现→bitstream→Program Device；按"怎么玩"3 步验证

## License

MIT License, see [LICENSE](LICENSE).
