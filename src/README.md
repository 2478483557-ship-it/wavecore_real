# src/ — 设计源码（RTL）

所有 FPGA 源码平铺在此目录。**规则：纯英文命名；仓库 UTF-8 / 工程 GBK（转换见 hw_analysis/to_gbk.py）。**

## 当前文件一览（2026-09-17）

```
src/
├── board_top.v        # 顶层：例化全部模块 + 串口行仲裁
├── dds_nco.v          # 32bit 相位累加器
├── sine_rom.v + sine_rom.hex      # 正弦查找表
├── dual_tone.v / freq_ctrl.v      # 双音控制 / 频率档位控制
├── da_send.v / ad_driver.v        # DA 时序 / AD 采样
├── freq_meter.v       # 测频+Vpp+占空比+脉宽（三层抗噪：2拍确认/施密特/5点中值）
├── measure_report.v   # 上行 F=/D= 两行（39字节连发）
├── fft_demo.v / fft_report.v / hann_rom.v(+hex)   # 4096点FFT → S=/A= 行
├── wave_frame.v       # 0x83 波形上传 + 0x89 触发（单写者+归零）
├── uart_tx.v / uart_rx.v / cmd_decoder.v / bin2bcd.v / div_restore.v
├── uart_mirror.v      # F1 转发口（镜像串口流给 STM32）
└── （存档，未参与综合）self_fft_1024.v / self_fft_report.v / twiddle_rom.v / tw_*.hex
```

## 代码规范

1. **文件头模板**（每个 .v 文件开头必须写）：模块名/功能/输入输出/时序说明/作者/日期/版本。
2. **命名规范**：文件名小写下划线；`rst_n` 低有效；参数名大写。
3. **编码风格**：
   - 时序逻辑统一 `always @(posedge clk or negedge rst_n)`
   - 一个 always 块只做一件事；**一个寄存器只允许一个 always 块写（单写者，防双驱动 DRC）**
   - 注释写"为什么"
4. **字符编码**：工程内 GBK，push 前转 UTF-8（脚本 `hw_analysis/to_gbk.py` 可双向）。
5. 关键模块配 testbench（`sim/`），先仿真后上板。
