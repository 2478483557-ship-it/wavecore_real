# 验证记录 · 2026-10-02：时基 T4 档（200 kHz）上板验证 + 构建数字更新

> 对应构建：**2026-10-02 10:44**（`rebuild_bitstream.bat` 10:40 启动，全流程约 4 分钟）
> 协议：**v1.20** ｜ 本次新增内容：频谱抛物线插值 + 时基 T4 档 + 谱帧看门狗修复（三项一起上板）

## 1. 构建核实（三条证据）

| 证据 | 结果 |
|---|---|
| 综合日志 | `synth_design completed successfully`，**0 Critical Warning / 0 Error**；日志中 `timebase` / `spec_compress` / `spec_buf` / `spec_frame` **各出现 4 次** → 新模块确实进了比特流 |
| 布线 | `fully routed nets = 13479 / 13479`，**# of nets with routing errors = 0** |
| 时序 | **All user specified timing constraints are met.** |

> ⚠️ 这一步不能省：`rebuild_bitstream.bat` 用的是 `add_files` 补文件（见 `rebuild_bitstream.tcl` 第 38 行
> `foreach f {spec_buf.v spec_compress.v spec_frame.v timebase.v}`），
> 若源码没同步到 D 盘工程，会**构建成功但功能缺失**。所以每次都核对"新模块在不在综合日志里"。

## 2. 资源与时序（对比上一版）

| 项 | 2026-10-01 09:42（0x8E 版） | **2026-10-02 10:44（本版）** | 差 |
|---|---|---|---|
| LUT | 6591（31.69%） | **7050（33.89%）** | **+459** |
| FF | 6925（16.65%） | **7326（17.61%）** | **+401** |
| BRAM | 11（22.00%） | 11（22.00%） | 0 |
| DSP | 28（31.11%） | **35（38.89%）** | **+7** |
| WNS | +1.835 ns | **+1.953 ns** | **+0.118（更好）** |
| WHS | +0.048 ns | +0.048 ns | 0 |
| 布线错误 | 0 | 0 | — |

**增量归因**：本版相对上一版多了三项改动 —— ① **频谱抛物线插值**（`USE_INTERP`，第 4 趟扫描 +
Q8 定标 δ 计算）、② **时基 T4 档**（`timebase.v` 加一个 `case` 分支）、③ **谱帧看门狗修复**（仅位宽）。
其中 **DSP +7 与插值引入的 32 位乘法相关**（`ic_fp = ic_x * fs_s`）；
LUT/FF 的增加来自插值状态机（3 个新状态）与 T4 分支。

> **资源增加而时序变好**：WNS 由 +1.835 → **+1.953 ns**。说明布局布线的余量本来就足，
> 这点增量没有触及关键路径。**31 条 DRC 无 Error、布线 0 错误**，设计仍然健康。

## 3. 板测结果

- **用户复验（2026-10-02 上午）：打开频谱图、放大后位置正确** ✅
- 时基四档判据（供后续复验引用，见 `board/verify_checklist.md` §9.1）：

| 档位 | Δf | 1kHz 应落 | 3kHz | 5kHz | 一键工具 |
|---|---|---|---|---|---|
| T1（默认）| 48.83 Hz | bin 20 | bin 61 | bin 102 | `run_waterfall_1k_sq.bat` |
| T2 | 12.21 Hz | bin 82 | bin 246 | bin 410 | `run_waterfall_T2.bat` |
| T3 | 97.66 Hz | bin 10 | bin 31 | bin 51 | `run_waterfall_T3.bat` |
| **T4** | **195.3 Hz** | **bin 5** | **bin 15** | **bin 26** | `run_waterfall_T4.bat` |

## 4. 本次一并确认的事实

- **模拟链路 -3 dB 带宽 > 1 MHz**（板载回环实测，1 MHz 处 −0.06 dB）→ T4 覆盖的 0~100 kHz
  完全落在链路平坦区内，**是真实的带宽扩展而非噪声放大**；详见 `report/link_bandwidth_measured.md`。
- **频谱量程的瓶颈在数字侧（decim），不在模拟侧** —— 若将来要覆盖 0~200 kHz，加 decim=125 档即可。

## 5. 遗留

- ⬜ GitHub 提交（本次改动含 T4 + 插值 + 看门狗 + 频响分析 + 4 份文档补齐，约 26 项）
- ⬜ 电压标定 KN 真值（0x8C，需外借万用表）—— 仍按原计划放在最后一步
