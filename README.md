# WaveCore

**基于 FPGA 的多功能信号测量与频谱分析系统**
A multi-function signal measurement & spectrum analysis system based on FPGA.

> 全国大学生嵌入式芯片与系统设计竞赛 2026 · FPGA 创新设计赛道（AMD）· 自主选题赛道（初级组）
> National Undergraduate Embedded Chip & System Design Competition 2026 · FPGA Innovation Track (AMD) · Self-Selected Topic (Junior Group)

---

## Features / 功能

| # | 模块 | 说明 | 状态 |
|---|------|------|------|
| 1 | DDS 信号源 | NCO（32 位相位累加器）+ 正弦查找表 → AD9708 输出 | 未开始 |
| 2 | ADC 采集 | AD9280 采样控制，外部信号数字化 | 未开始 |
| 3 | 自动测量 | 频率 / 周期 / 幅度 / Vpp 一键测量 | 未开始 |
| 4 | FFT 频谱 | 1024 点 FFT，双模式（测量 / 音频） | 未开始 |
| 5 | 音频频谱（彩蛋） | 麦克风 → XADC → FFT → LED 频谱条 | 未开始 |
| 6 | 数据打包 + UART | 波形 / 频谱 / 测量结果打包成帧发送上位机 | 未开始 |

## Hardware / 硬件平台

- 正点原子达芬奇 Pro（AMD Artix-7 XC7A35T）
- ATK_HS_AD_DA 模块（AD9708 DAC / AD9280 ADC）
- STM32F407（人机交互，转发数据到串口屏）
- 淘晶驰串口屏（板载显示）
- 驻极体麦克风（音频彩蛋，接板载 XADC）

## Environment / 开发环境

- Vivado **2020.1**（注：赛题推荐 2026.1 / 2025.2，本工程使用 2020.1 的原因与脚本可复现性说明见 `report/design_report_outline.md`）
- 仿真：Vivado XSim / ModelSim

## Directory Structure / 目录结构

```
wavecore/
├── README.md          # 项目简介 + 复现步骤
├── LICENSE            # MIT 开源协议
├── src/               # 设计源码（RTL）
├── sim/               # 仿真 testbench 与结果
├── build/             # 构建脚本（tcl）+ 综合/实现报告
├── board/             # 上板工程、实测输出与记录
├── data/              # 测试数据与参考结果
├── skill/             # 技能包（踩坑清单，LLM 经验沉淀）
└── report/            # 设计报告 + 大模型协作记录
```

## How to Reproduce / 复现步骤

（按开发进度逐步完善，最终需做到"他人可从零复现"）

1. 安装 Vivado 2020.1（支持 Artix-7）
2. 克隆本仓库：`git clone <repo-url>`
3. 打开 `build/` 中的 tcl 脚本（或 `.xpr` 工程）创建工程
4. 依次综合、实现、生成比特流，下载到达芬奇 Pro
5. 按 `board/README.md` 的步骤连接 ATK_HS_AD_DA 模块并验证各功能

## License

MIT License, see [LICENSE](LICENSE).
