# 2026-09-16 战报与待办清单（WaveCore）

> 提交建议 Summary: `feat: duty/pulse + shapes + trigger + baud460800 + self-FFT(on-demand); docs: SK-017~020`

## ✅ 今日完成（标记 = 验证状态）
| # | 事项 | 状态 | 证据 |
|---|---|---|---|
| 1 | **占空比 + 脉宽测量**（计窗统计法，freq_meter v4）| ✅ 上板验证 | 方波 1kHz：D=49.8~50.0%、W=499~500us；100kHz：D≈50%、W=5us |
| 2 | **方波/三角波输出**（0x88，v1.6）| ✅ 上板验证 | 方波全链路稳定、FFT 谐波符合预期 |
| 3 | **触发采集**（0x89 自由/上升/下降）| ✅ **上板验证通过**（9/17 早）：B上升→前6点全高、C下降→前6点全低 | 迭代4次：ST_FILL→绕圈→单写者归零(SK-021) |
| 4 | **串口提速 460800**（v1.8）| ✅ 实测生效 | 波形帧 90ms→22ms；XCOM 460800 正常 |
| 5 | **协议 v1.5→v1.10**（D/W 行、0x88、0x89、0x8A、SF 行、460800）| ✅ | 见 `board/uart_protocol.md`＋§6 速查表 |
| 6 | **自研 1024 点 RTL FFT**（F4）| 🔶 RTL 完成+金标准验证；**按需 0x8A**（默认静默）| 金标准：1kHz→bin20 ✅；SF 行待上板确认 |
| 7 | **自研 FFT 设计档案（含褒贬）** | ✅ | `report/self_fft_design.md` |
| 8 | **技能包 SK-017/018/019/020**（计窗法/暂态收敛/方波-正弦差异/大逻辑静默化）| ✅ | `skill/README.md` |
| 9 | **诊断工具**：`check_duty.py`（PC 独立审计）、Z 心跳、LED 心跳、状态码探针 | ✅（探针为临时件）| `host/check_duty.py` |
| 10 | **正弦专项排查**（进行中）：方波完美 vs 正弦不稳 | 🔶 已做 A/B 大框架；最终结论待"正弦专项 A/B"测完 | 见下"待办 1" |

## 🔶 待办（按优先级）
1. **正弦专项 A/B 定性**（10 分钟）：1kHz 正弦 vs 100kHz 正弦，各抄 F + 抓图（clean? 毛刺?）→ 判定"数字侧 or 模拟侧"；之前"FFT 噪声干扰"推断**挂起待改**
2. **SF 行确认**：`0x8A` 发一次 → 是否出现 `SF=0000976`（1kHz）并对照 IP 的 `S=0001001`
3. **触发验证**：`0x89 01` → `0x83` → 波形从上升沿开始（vs 自由模式对比）
4. **清理临时探针**：Z 心跳、LED4 心跳、状态码调试（全绿后删除）
5. **资源对比表**：自研 FFT vs xfft IP（LUT/FF/BRAM/DSP/耗时/分辨率）——答辩素材
6. **固化新版**（Flash, mt25ql128，功能定稿后一次性做）
7. **文档线**：LLM 原始交互记录存档；报告章节（技能包提炼过程/优化对比/复现说明/工具版本说明）
8. （可选）ILA 恢复、测频抗噪增强、100kHz 脉宽取整四舍五入

## 📦 提交清单（本次应包含的改动）
- `src/`: freq_meter.v(v4) / measure_report.v(v3.2) / cmd_decoder.v / board_top.v / wave_frame.v(触发) / self_fft_1024.v / self_fft_report.v / twiddle_rom.v / uart_tx.v / uart_rx.v + `tw_*.hex`
- `board/uart_protocol.md`(v1.10) / `board/README.md`
- `host/`: check_duty.py(新) / wave_plot_example.py / serial_monitor_starter.py(460800)
- `skill/README.md`(SK-017~020)
- `report/`: self_fft_design.md(新) / backlog.md / teammate1/2_task.md / task_overview.md / host_code_review_2026-09-15.md(新)

## ⏸ 挂起项（明确不删）
- **[9/16 22:2x 更新] 隔离实验结论**：移出自研FFT后，**正弦全频段恢复稳定**（100k/200k/500k/1M/1kHz F 全部精确）→ FFT 干扰被隔离实验证实；继续维持移出状态
- **[9/16 22:0x 更新] 自研FFT 已从设计临时移出**（board_top 中 u_scfft/u_sfrpt/mux/led 心跳全撤，Z 心跳随之消失）；协议 v1.11 标注 SF/0x8A 暂无效；源码保留、重启步骤见 `report/self_fft_design.md` §7
- "正弦高频不稳"最终归因（等 A/B）
- "自研FFT噪声干扰"假设（改为"待定/已弱化"，A/B 后定稿）
- ILA（资源腾挪后再启）
