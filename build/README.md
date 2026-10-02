# build/ — 构建脚本 + 综合与实现报告

## 内容

- `create_project.tcl` — **一键从零复现脚本**（2026-09-27 生成；用法：在 Vivado Tcl Console 里 `source build/create_project.tcl`）
  - 自动：建工程(xc7a35tfgg484-2) → 拷贝 RTL 并**重写 $readmemh 绝对路径** → 加约束 → 重建 3 个 IP（blk_mem_gen_0/1、xfft_0）
  - 注意：不重建 ila_0（调试用，交付版已移除）；blk_mem_gen_1 的读延迟口径见 SK-025
- `reports/` — 综合与实现报告（已从正式工程导出）
  - `board_top_utilization_placed.rpt`（资源：LUT 33.89% / FF 17.61% / BRAM 22% / DSP 38.89%）
  - `board_top_timing_summary_routed.rpt`（时序：WNS +1.953ns）
  - `util_hier.rpt`（分层资源：各模块 LUT/DSP 明细）
- 资源占用记录表（下面有模板）

## 资源占用记录表（每完成一个模块更新一次 —— 评分项"性能与资源优化"20% 的素材）

| 日期 | 模块 | LUT | FF | DSP | BRAM(36Kb) | Fmax(MHz) | WNS(ns) | 备注 |
|------|------|-----|----|----|------|-----------|---------|-------|------|
| - | 空工程基线 | - | - | - | - | - | - | - |
| 2026-09-03 | M2 DDS 1MHz（board_top） | 42 | 31 | 0 | 0 | 理论≈448（50MHz 约束下裕量巨大） | Setup +17.769 / Hold +0.251 / Pulse +9.5 | 附加：F7=11, F8=5, Slice=18, IOB=11, BUFG=1；正弦 ROM 用 LUT(case) 未用 BRAM |
| - | - | - | - | - | - | - | - | - |

> XC7A35T 总资源：LUT 20800 / FF 41600 / DSP 90 / BRAM 50 块（1350Kb）。
> 资源使用率不是越高越好，合理即可，报告里要写"为什么这样用"。

## 复现步骤（暂定，逐步完善）

1. 启动 Vivado 2020.2（或更新的兼容版本）
2. Tcl Console 执行：`source build/create_project.tcl`
3. 综合 → 实现 → 生成比特流（预期资源见 reports/）
