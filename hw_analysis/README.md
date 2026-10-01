# hw_analysis/ —— 验证脚本与数值金标准（开发期工具）

> **2026-10-01 从工作区收进仓库。** 此前这 14 个脚本一直放在 git 仓库**外面**，
> 而 `skill/README.md`、`report/`、`board/`、`src/`、`README.md` 里 **60 多处**引用它们
> （典型写法："期望值来源：`hw_analysis/probe_interp.py`"）—— 引用是**悬空**的。
> 现在脚本随仓库走：任何人 clone 下来，都能自己复现我们论文/报告里报出的每一个数字。
> 这是"可复现性"最便宜的一块证据。

## 脚本清单

| 脚本 | 作用 | 什么时候必须跑 |
|---|---|---|
| `probe_interp.py` | 自研 FFT **频谱抛物线插值**数值模型（与 RTL 同口径） | 改插值公式 / 加窗 / 取峰判据后 |
| `probe_tb_scenarios.py` | 重算回归场景的**期望值** | 改任何算法后（**SK-037**） |
| `probe_dual_ordering.py` | 蝶形"读-读-算-写"调度与金标准逐步对比 | 改 FFT 调度后 |
| `verify_hann_window.py` | Hann 窗数值验证（**先复现板上故障，再验证修复**） | 改窗函数 / 换窗长后 |
| `verify_spectrum_frame.py` | 0x8E 幅度谱帧的**整数级金标准**（含压缩码逐 bin） | 改压缩 / 改帧格式后 |
| `check_self_fft_overflow.py` | 频率换算**位宽溢出**全 bin 扫描（0 错才算过） | 改位宽 / 换点数 N 后 |
| `verify_freq_conv_fix2.py` | 位宽溢出 bug 的复现与修复验证 | 同上 |
| `check_protocol_frames.py` | 协议帧**审计器**：抠出 md 里所有 HEX 帧，逐条核 LEN 与校验和 | 改 `board/uart_protocol.md` 后**必跑** |
| `gen_hann_rom.py` | 生成 `src/hann_rom.v` 里的窗表 | 改窗长（如 1024 → 4096）后 |
| `gen_sine_rom.py` | 生成 `src/sine_rom.v` 里的正弦表 | 改波表后 |
| `to_gbk.py` | 仓库(UTF-8) → Vivado 工程(GBK) 的单批文件转换（早期版本） | 见下 |
| `sync_src_gbk.py` | 同上，**全量版**（逐文件比对 + 报告差异） | **每次改 RTL 后** |
| `scan_eol_style.py` | 换行 / BOM 体检（提交前必过） | 每次提交前 |
| `deploy_scripts.py` | 把一键 `.bat` 部署到 D 盘工程根 | 改了 `.bat` 后 |

## 怎么跑

```bat
REM 本项目所有上位机/脚本统一用**系统 Python 3.8**（托管 3.13 没装 pyserial/numpy）
C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe check_protocol_frames.py
```

- 依赖：以标准库为主；`probe_interp.py` 用到 numpy（3.8 环境已装）
- **路径约定**：脚本统一用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
  反推仓库根 —— 2026-10-01 已把 5 处**写死的开发机绝对路径**（`C:/Users/.../wavecore`）改掉，
  所以**整个仓库可以搬到任何目录/任何机器**再跑
- 数据来源（`hann_1024.hex`、`uart_protocol.md` 等）都在仓库内，**不依赖 D 盘工程**

## 注意

- 这里只留**可复用**的验证 / 生成脚本。一次性的"改文档"补丁脚本
  （`patch_*.py`、`update_*.py`、`fix_*.py` 之类，共 60 多个）留在开发工作区，**不入库** ——
  否则仓库会变成一个没人看得懂的一次性脚本垃圾场。
- **金标准会"说谎"**：脚本与 RTL 是两份代码，改了一边没改另一边，脚本就会报出过时的"期望值"。
  所以规矩是：**改 RTL 公式 → 同步改对应脚本 → 重跑 → 再把新期望值抄进 tb / 文档**（SK-037）。
- 2026-10-01 实跑验收：`check_protocol_frames.py` → **44 条帧 0 问题**；
  `scan_eol_style.py` → **185 个文件全部纯净（无 BOM、无行内混排）**；
  `probe_interp.py` → 1kHz 方波 977/2979/4980 → **999.4/2998.4/4997.8**（真值 1000/3000/5000）。
