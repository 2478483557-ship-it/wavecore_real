# 证据索引表

> **这张表回答一个问题：文档里每一个数字，是怎么测出来的？**
>
> 用法：评委/复现者拿到某个结论，按表找到「测试条件 → 脚本 → 原始输出 → 截图」四件套，
> 自己跑一遍就能复现。所有脚本都在本仓库内，不需要外部仪器。
>
> 最后核对：2026-10-25 ｜ 对应提交版本 `submission-v1.0`

---

## 一、怎么用这张表

每条结论都按同一结构给出四样东西：

| 列 | 含义 |
|---|---|
| **结论** | 文档里写的那句话 |
| **测试条件** | 什么样的信号、什么设置、什么前提 |
| **脚本** | 跑哪个文件能得到这个数 |
| **原始数据 / 证据** | 脚本打印什么、看屏幕哪个位置、或图几 |

**约定**：标 `[上板]` 的是实机测出来的；标 `[仿真]` 的只在仿真里成立，文档里必须注明。
**这两类不混用**——这是本项目的硬规矩。

---

## 二、测量类

| # | 结论 | 测试条件 | 脚本 | 原始数据 / 证据 |
|---|---|---|---|---|
| M1 | 频率 100Hz~1MHz 误差 <1% | 回环正弦，1k/5k/37.5k/100k/1M 五点 | `host/regression_2026_10_23.py` | 打印 `F=` 与设定值逐字比对，26 项全 PASS |
| M2 | 1kHz 读数 999Hz（不是 1000） | 1kHz 方波，自研 FFT，Hann 窗 + 插值 | `host/check_interp.py` | 打印 976（插值前）→ 999（插值后） |
| M3 | 电压 1~4V 最大偏差 2.8%、平均 0.8% | 外部信号源送入 1/2/3/4V | `host/regression_2026_10_23.py` | `V=` 与万用表读数逐点比对；标定表见 `report/accuracy_calibration.md` |
| M4 | 预触发四档 0/256/512/768 逐点精确 | 1kHz 方波，四档各采一帧 | `host/check_pretrigger.py` | 统计帧内低电平点数，`report/figures/fig_pretrigger_tiers.png` |
| M5 | 占空比 49.9~50.4% | 1kHz 方波 | `host/check_duty.py` | 打印 `D=` 连续采样分布 |
| M6 | 幅度谱帧率 21.2 帧/s（效率 91%） | T1，持续请求 0x8E | `host/check_framerate.py` | 计时 100 帧，47.2ms/帧 |

## 三、频谱类

| # | 结论 | 测试条件 | 脚本 | 原始数据 / 证据 |
|---|---|---|---|---|
| F1 | 泄漏 14.7% → 0.9% | 1kHz 方波，矩形窗 vs Hann 窗 | `hw_analysis/verify_hann_window.py` | 打印旁瓣比与泄漏百分比；`report/figures/` 无图则看脚本输出 |
| F2 | 插值把 976 → 999Hz | 同上，开 `USE_INTERP` | `hw_analysis/probe_interp.py` | 打印插值前后 bin 与频率 |
| F3 | 定点 FFT vs float64：RMSE 1.24×10⁻³（−58dB） | 正弦/方波/小幅三组，逐 bin 比对 | `hw_analysis/fixed_vs_float_fft.py` | 打印每组 RMSE、峰值 bin 是否一致 |
| F4 | 三峰 999 / 2998 / 4997 | 1kHz 方波，0x8A | `host/regression_2026_10_23.py` | 串口 `SF= / S2= / S3=` 三行；判据 ±1 bin |
| F5 | 高频单峰误差 <0.03% | T3/T4，1/2/5MHz | `host/regression_2026_10_23.py` | 打印实测 vs 设定（如 1MHz→1000237） |
| F6 | 第三峰越界会折叠成 fs−f | 5kHz 方波，T1 | `host/diag_three.py` | 打印 5f 理论值与第三峰读数；`report/figures/` 表见文档 §3.3 |
| F7 | **★** 谱平均：帧间标准差 14.5 → 1.05，底噪均值不变 | 8 帧平均，同一信号连续 20 帧 | `host/spectrum_waterfall.py` 或 `hw_analysis/` | **注意：不是"底噪降 4.5dB"**，见本表第七节"已撤销的说法" |

## 四、识别类

| # | 结论 | 测试条件 | 脚本 | 原始数据 / 证据 |
|---|---|---|---|---|
| R1 | 自动选源 1k~200kHz 三波形 18/18 | 3 波形 × 6 频点（1k/10k/30k/100k/150k/200k） | `host/measure_ty_vs_freq.py` | 打印每个频点三种来源（自动/规则法/NN）的判定分布 |
| R2 | 规则法上限：正弦 150k / 方波 400k / 三角 100k | 扫频 + 连续采样统计正确率 | `hw_analysis/rule_vs_nn_sweep.py` | 打印每种波形每频点的正确率矩阵 |
| R3 | 神经网络上限：正弦 400k / 方波 200k / 三角 200k | 同上 | `hw_analysis/nn_freq_sweep.py` | 同上 |
| R4 | NN 定点权重与浮点一致 | 2000 条训练样本 | `hw_analysis/train_wave_nn.py` | 打印定点化前后的分类一致率 |

## 五、锁相类

| # | 结论 | 测试条件 | 脚本 | 原始数据 / 证据 |
|---|---|---|---|---|
| L1 | −18.8dB SNR 下误差 0.8%（真值 290mV，锁相 288mV） | 1kHz 正弦，噪声 level=8 att=4，积分 32 周期 | `host/scan_lockin_snr.py` | 打印每个 SNR 点的真值/直接测量/锁相三列；`report/lockin_snr_curve.md` |
| L2 | 同一时刻直接测量偏 12 倍（3487mV） | 同 L1 | 同上 | 同一行里的 `V=` 列 |
| L3 | 中间点 −0.6dB 误差 3.1%、−12.8dB 误差 1.2% | 同 L1，改 level/att | 同上 | 同上 |
| L4 | 满幅加噪锁相偏 21.9% | 不衰减直接加噪 | `host/demo_weak_signal.py` 第 0 步之后 | **这是削顶，不是锁相失效**，见 `report/lockin_snr_curve.md` §8 |
| L5 | I/Q 帧换算正确（66 码, N=800000, 45° → 4796mV/45°） | 软件构造帧 | `host/test_lockin.py` | 打印手算值与界面值对比 |

## 六、资源与时序

| # | 结论 | 测试条件 | 来源 | 证据 |
|---|---|---|---|---|
| S1 | LUT 7886（37.91%）/ FF 7082 / BRAM 12 / DSP 40 | Vivado 2020.2，实现后 place | `<工程根>/wavecore.runs/impl_1/board_top_utilization_placed.rpt`（**构建产物，不入库**） | **必须看 placed 报告**，不能看综合估计 |
| S2 | WNS +0.613ns、WHS +0.057ns、0 失败端点 | 同上 | `<工程根>/wavecore.runs/impl_1/board_top_timing_summary_routed.rpt` | 设计摘要表（Design Timing Summary） |
| S3 | 自研 FFT 502 LUT / 346 FF / 7 DSP | OOC 综合该模块 | `report/resource_compare.md` | 与 IP 核 1771 LUT / 9 DSP 同口径 |
| S4 | 资源攻坚 20829 → 5117 LUT（−75.4%） | 改 SDP 模板前后各一次实现 | `report/lut_slim_report.md` | 两次 placed 报告对比 |

> ⚠️ **三种资源报告口径不同，不能混用**：综合报告（IP 当黑盒）、层次报告（全含 ILA）、
> 实现报告（真实上片）。对外只引用实现报告。

## 七、已撤销的说法（★ 这一节是给评委看的）

项目过程中有三条结论**被我们自己的实测推翻**，都保留了修正记录：

| 原说法 | 实际情况 | 在哪改的 |
|---|---|---|
| "双 FFT 互为参照，可互相校验" | IP 核在抽取比 <100 时无法完成一帧，只能服务 0~25kHz；自研核覆盖到 6.25MHz，**两者从不在同一频段** | README §工程亮点、技术文档 §1.3(1)、答辩稿 Q2 |
| "谱平均使底噪下降约 4.5dB" | 平均只降方差、不改变均值。实测帧间标准差 14.5→1.05，**底噪中位数基本不动** | README、技术文档 §3.3(6) |
| "锁相在 −13dB 下误差 2.1%" | 真值算法用 `基准/2^att` 计算，但衰减是整数右移有截断（67>>4=4 码≈290mV，不是 304mV），4.6% 误差被算到锁相头上。改正后 **−18.8dB 下 0.8%** | `report/lockin_snr_curve.md` §8、技术文档 §3.3(10) |

**为什么保留这些**：能说出自己哪里错、怎么发现的，比只展示正确结论更能说明这东西是真的。

## 八、复现顺序（照着跑一遍约 15 分钟）

```bash
# 0. 前置：板子插 USB、接回环飞线、Flash 已固化
#    上位机需 Python 3.8（含 pyserial/numpy/matplotlib）

1  host\run_demo_reset.bat                  # 复位到 1kHz 正弦
2  host\regression_2026_10_23.py            # 26 项回归，全 PASS 说明基本功能正常
3  host\check_interp.py                     # 复现 976→999
4  host\check_pretrigger.py                 # 复现四档 0/256/512/768
5  host\run_demo_weak.bat                   # 复现锁相 −18.8dB / 0.8%（三步交互）
6  hw_analysis\verify_hann_window.py        # 复现泄漏 14.7%→0.9%（纯计算，不用板子）
7  hw_analysis\fixed_vs_float_fft.py        # 复现 RMSE 1.24e-3（纯计算）
```

> S1/S2 的两份 .rpt 是 Vivado 实现产物（`wavecore.runs/impl_1/`），**不入库**——
> 复现者需自己综合一次才能得到。仓库里同步保存了同一批数字的快照：`report/resource_compare.md`。

**不用板子也能复现的**：F1、F3、R2、R3、S3（纯计算/综合报告）。
**必须上板的**：M1~M6、F4~F6、R1、L1~L5。

---

## 九、这张表本身的维护规则

1. **加新结论 → 必须同时补一行**，否则文档里出现"查无此项"的数字。
2. **脚本改名 → 同步改表**。表里的路径是唯一索引。
3. **结论被推翻 → 不删原行，移到第七节**，保留修正轨迹。
4. **数字冻结**：打 `submission-v1.0` 标签后，本表与技术文档、视频字幕三处数字必须一致。
