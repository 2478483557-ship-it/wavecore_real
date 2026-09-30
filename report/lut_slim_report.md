# LUT 超限诊断与瘦身方案

> 触发：2026-09-30 `place_design` 报 `ERROR: [DRC UTLZ-1]`，Slice LUTs 超限。
> 结论：**超的量极小（29 个 LUT），但根因是一处结构性问题；修完顺带省下约 8000 个 LUT。**
> 相关文档：`board/vivado_gui_troubleshoot.md`、`sim/fft_demo_check/`、`skill/SK-016`

---

## 1. 先把数字对准：到底超了多少

| 阶段 | Slice LUTs | 占 20800 |
|---|---|---|
| 综合 (`report_utilization`, 11:10) | **19231** | 92.46% —— 看起来没事 |
| `opt_design` 之后 (11:14) | **20829** | **100.14% → 超 29 个** |

`wavecore.runs/impl_1/runme.log:177`：

```
ERROR: [DRC UTLZ-1] Resource utilization: Slice LUTs over-utilized in Top Level Design
(This design requires 20829 of such cell types but only 20800 compatible sites are available)
ERROR: [Vivado_Tcl 4-23] Error(s) found during DRC. Placer not run.
```

**教训一：不要用综合的资源数判断"能不能布得下"。**
`opt_design` 为了优化时序会做 retarget / 逻辑复制 / 常量传播，这次它把 19231 涨到了 20829（+1598）。
"综合 92.46% 过了" ≠ "实现能过"。

---

## 2. 根因：`fft_demo` 里的 `f_ram` 没进块 RAM

### 2.1 分层资源，一眼看穿问题在哪

`build/reports/util_hier.rpt`（2026-09-20，`-hierarchical`）：

| 实例 | 模块 | Total LUTs | FFs | RAMB18 |
|---|---|---|---|---|
| **board_top** | (top) | 20479 | 38079 | 16 |
| **u_fft_demo** | **fft_demo** | **17564 (86%)** | **35558 (93%)** | 12 |
| ├ (u_fft_demo) | fft_demo 自身逻辑 | **15793** | **33008** | **0** |
| ├ u_fft | xfft_0（官方 FFT IP） | 1771 | 2550 | 11 |
| └ u_hann | hann_rom | 0 | 0 | 1 |
| u_meter | freq_meter | 744 | 616 | 0 |
| u_report | measure_report | 638 | 155 | 0 |
| u_scfft | self_fft_1024 | 502 | 346 | 2 (+1 RAMB36) |
| 其余全部模块 | | 各 < 250 | | |

**一个 4096 点 FFT 引擎，自己写了 15793 个 LUT、33008 个触发器。**
官方 IP 只用了 1771 LUT / 2550 FF。多出来的部分不是 FFT，是**缓存**。

### 2.2 三百行代码，一眼定位到那一个数组

`src/fft_demo.v` 里只有一处大存储：

```verilog
(* ram_style = "block" *) reg [7:0] f_ram [0:4095];    // 4096 x 8 = 32768 bit
```

对账：

| 项 | 数值 |
|---|---|
| `u_fft_demo` 自身 FFs | 33008 |
| `f_ram` 容量 | **32768** |
| 差 | **240** |
| 手工加总 `fft_demo.v` 里除数组外的全部寄存器 | **233** |

**32768 + 233 ≈ 33008。差值 240 落在 7 个寄存器的误差内（推测器/状态机重编码）。**

### 2.3 两条硬证据

**证据 A —— 已布线的时序报告里它叫 `f_ram_reg`，类型是 `FDRE`：**

`build/reports/board_top_timing_summary_routed.rpt:196`

```
Destination:            u_fft_demo/f_ram_reg[3025][5]/D
    SLICE_X4Y63          FDRE        r    u_fft_demo/f_ram_reg[3025][5]/D
```

`FDRE` = 触发器。不是 RAMB，不是 LUTRAM。

**证据 B —— BRAM 账目对不上：**

`util_hier.rpt` 里 `u_fft_demo` 的 RAMB18 = 12 = xfft 11 + hann 1。
**`f_ram` 贡献 0 个 BRAM。** 同表的 `LUTRAMs` 列，全设计都是 0 —— 也**不是分布式 RAM**。

综合报告 `board_top_utilization_synth.rpt` 里 `LUT as Memory = 0`，同样是 0。

结论：`f_ram` 被综合成了 **32768 个触发器**。

### 2.4 代价有多大：连读口的 mux 一起算

32768 个触发器要读出来，需要一个 **4096:1 × 8 bit** 的组合多路器。7 系列里
16:1 多路器 = 4 个 LUT6 + 2 个 MUXF7 + 1 个 MUXF8（正好占一个 slice）。所以：

| 资源 | 估算占用 | 全设计实际用量 | 占比 |
|---|---|---|---|
| LUT6 | ≈ 4096/16 × 4 × 8 = **8192** | 15164 | **54%** |
| MUXF7 | ≈ 4096/16 × 2 × 8 = **4096** | **4379** | **94%** |
| MUXF8 | ≈ 4096/16 × 1 × 8 = **2048** | **2180** | **94%** |

MUXF7 / MUXF8 的实测值与估算几乎完全吻合 —— 这两个数字本身就是铁证。

---

## 3. 为什么 Vivado 不肯把它推断成块 RAM

同一条综合日志里，`uart_mirror` 给出了标准答案：

`wavecore.runs/synth_1/runme.log:200`

```
Reason is one or more of the following :
	1: RAM is sensitive to asynchronous reset signal. this RTL style is not supported.
RAM "fifo_reg" dissolved into registers
```

**"RAM 的输出寄存器带异步复位" —— Vivado 明确不支持这种写法。**

`f_ram` 的读口正是这个写法：

```verilog
// 旧写法（问题所在）
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) m_q <= 8'd0;                                  // ← 异步复位，致命
    else if (st == ST_CFG && cfg_tready) m_q <= f_ram[14'd0]; // ← 常量地址读
    else if (st == ST_FEED && s_data_tready && rd_idx != NFFT-1)
        m_q <= f_ram[rd_idx + 14'd1];
end
```

除了异步复位，还有三处隐患叠加：

1. `f_ram[14'd0]` —— 常量的 0 地址读，和变量地址读混在同一个 always 里；
2. 写口 `f_ram[wr_idx] <= ad_cap;` 混在主状态机的大 always 里；
3. 地址位宽 14 位，但数组深度只有 4096（12 位）。

### 3.1 一个值得记住的细节

翻 `skill/README.md` 的 SK-015 记录，**2026-09-05 就"修"过一次**：

> FDRE 需 77108>65950 → f_ram 改块 RAM；LUT 21775>20800 → hann 改 readmemh 块 ROM → 最终 **LUT 19282 / BRAM 7**

但今天的报告显示 LUT = 19231、`f_ram` 仍是 FDRE。
**说明当年真正起作用的是"hann 改 readmemh 块 ROM + 删掉那块 4096 深幅度缓存"，
`f_ram` 的块 RAM 推断从来没成功过** —— 当时 LUT 恰好降到 19282（和今天 19231 几乎一样），
问题被掩盖了 25 天。

> **教训二：`ram_style = "block"` 是个"愿望"，不是"保证"。**
> 写了属性不等于进了 BRAM。**必须回头看资源报告里的 `RAMB18/RAMB36` 列**，
> 数组没有出现在那里 = 没进 BRAM。

---

## 4. 改法：改成教科书 Simple-Dual-Port 模板

`src/fft_demo.v` v3.3 的三处改动（只动存储端口，**不改任何算法和时序**）：

```verilog
// 1) 写口：从主状态机里拆出来，独立 always，**不带任何复位**
wire        wr_en_w   = (st == ST_CAP) && (decim_cnt == DECIM - 32'd1);
wire [11:0] wr_addr_w = wr_idx[11:0];          // 深度 4096 → 地址截到 12 位
always @(posedge clk)
    if (wr_en_w) f_ram[wr_addr_w] <= ad_cap;

// 2) 读口：独立 always，单条无条件读，**去掉异步复位**
wire        rd_en_w   = (st == ST_CFG && cfg_tready) ||
                        (st == ST_FEED && s_data_tready && rd_idx != NFFT - 1);
wire [11:0] rd_addr_w = (st == ST_CFG) ? 12'd0 : (rd_idx[11:0] + 12'd1);
always @(posedge clk)
    if (rd_en_w) m_q <= f_ram[rd_addr_w];

// 3) ST_CAP 里那句 f_ram[wr_idx] <= ad_cap; 删掉（已挪到写口）
```

### 4.1 为什么行为完全不变

| 状态 | 旧写法 | 新写法 |
|---|---|---|
| `ST_CAP`，`decim_cnt==DECIM-1` | 写 `f_ram[wr_idx]` | `wr_en_w=1`，写 `f_ram[wr_idx[11:0]]` ✅ 同 |
| `ST_CFG && cfg_tready` | `m_q <= f_ram[0]` | `rd_en_w=1`，`rd_addr_w=0` ✅ 同 |
| `ST_FEED && tready && rd_idx!=4095` | `m_q <= f_ram[rd_idx+1]` | `rd_en_w=1`，`rd_addr_w=rd_idx+1` ✅ 同 |
| 其余时刻 | `m_q` 保持 | `rd_en_w=0`，`m_q` 保持 ✅ 同 |

关键点：**旧的"组合读触发器数组 + 打一拍"和"同步读 BRAM（1 拍延迟）"在时序上完全等价**
—— 旧的 `f_ram[addr]` 是直接接到 `m_q` 的 D 端的组合逻辑，`m_q(T+1) = f_ram[addr(T)]`；
BRAM 也是 `doutb(T+1) = mem[addrb(T)]`。一模一样。

`m_q` 现在上电是 `x`，但复位后要跑满 `4096 × DECIM` 拍才进 `ST_CFG`，早就刷成有效值。
且 `m_q` 只在 `ST_FEED` 参与运算。

### 4.2 预期收益

| 指标 | 现在 | 改后（预期） |
|---|---|---|
| Slice LUTs | 19231 → opt 后 **20829（超）** | ≈ **12600（61%）** |
| Slice Registers | 35818（86.10%） | ≈ **3050（7%）** |
| MUXF7 / MUXF8 | 4379 / 2180 | ≈ 280 / 130 |
| RAMB18 | 4 | 6（`f_ram` 占 2） |

顺带好处：
- **布线余量打开** —— 当初 ILA 就是因为"布局余量不足"被禁用的（`board_top.v:344`），现在可以重新打开；
- 给 P2 的 `0x8D 时基档位` / `0x8E 幅度谱帧` 留出了资源空间；
- 竞赛评分"资源使用"（20 分）从"几乎撑爆"变成"调优后大幅下降"，是很好的加分点。

### 4.3 实测结果（2026-09-30 13:56 已确认，本方案生效）

综合 + 实现 + 比特流全部跑通。**实测值比我上面那张"预期表"还好，但我的预期本身是错的**（低估了）——
原因见下面 4.3.2，这个错误本身也是个值得记录的教训。

#### 4.3.1 改造前 / 改造后（实现阶段真实数字）

| 指标 | 改造前 | 改造后 | 变化 |
|---|---|---|---|
| **Slice LUTs**（`opt_design` 后 / 布局完成） | **20829（100.14%）—— 超 29 个，`place_design` 直接报错退出** | **5117（24.60%）** | **−75.4%** |
| **Slice Registers** | 35818（86.10%） | **4834（11.62%）** | **−86.5%** |
| F7 Muxes | 4379 | **21** | −99.5% |
| F8 Muxes | 2180 | **4** | −99.8% |
| RAMB36E1 | 0 | **1**（就是 `f_ram` 本体） | +1 |
| WNS | +1.395 ns | **+2.087 ns** | 时序更宽松（这是本轮构建值；当日为消假峰改 `GAP` 后重建为 **+1.689 ns**，其余数字均不变） |
| 布线 | `place_design` 阶段 `[DRC UTLZ-1]` 报错中止 | **0 个布线错误**（9271/9271 全布通） | 通过 |

综合口径（`synth_1/board_top_utilization_synth.rpt`，13:56）：
LUT `19231 → 3702`，Registers `35818 → 2443`，F7/F8 `4379/2180 → 11/4`。

实现五步全部 `completed successfully`：`opt_design`(13s) → `place_design`(21s) →
`phys_opt_design` → `route_design`(27s) → `write_bitstream`(13s)。
时序 `WNS +2.087 / TNS 0 / WHS +0.065 / THS 0`，`All user specified timing constraints are met.`
（以上为**第 1 轮**构建值；当日下午加 `GAP=6` 消除矩形窗假峰后重建，`WNS +1.689 / TNS 0 / WHS +0.052 / THS 0`，同样全收敛，LUT/Reg/BRAM/DSP 一个数没变。）
（以上为**第 1 轮**构建值；当日下午加 `GAP=6` 消除矩形窗假峰后重建，`WNS +1.689 / TNS 0 / WHS +0.052 / THS 0`，同样全收敛，LUT/Reg/BRAM/DSP 一个数没变。）
DRC 共 87 条，**全部是 Warning，零 Critical、零 Error**。
产物 `impl_1/board_top.bit`，2,192,117 B。

#### 4.3.2 铁证：同一个信号名，从 `FDRE` 变成 `RAMB36E1`

改造前，在**已布线**的时序报告里是：

```
Destination: u_fft_demo/f_ram_reg[3025][5]/D   ...   SLICE_X4Y63  FDRE
```

改造后，在 DRC 报告里是：

```
The RAMB36E1 u_fft_demo/f_ram_reg has an input control pin
    u_fft_demo/f_ram_reg/ADDRARDADDR[10] (net: u_fft_demo/wr_idx[7]) ...
```

**同一个实例名 `u_fft_demo/f_ram_reg`，前者的类型是 `FDRE`（触发器），后者是 `RAMB36E1`（36 Kb 块 RAM）。**
这是"我改的那一个东西真的变了"最直接的证据 —— 也正是 9/5 那次"假修复"从来没提供过的证据。

#### 4.3.3 我的预期错在哪（教训）

我预计 LUT 降到 11000~13000，实测 5117，**降幅比我估计的大一倍多**。两个原因：

1. **我漏算了写口的 4096 路地址译码。** 一个 4096 深的数组退化后，不只读口有 4096:1 mux，
   写口还要给 4096 个触发器各做一份写使能译码。我只算了读 mux（约 8192 个 LUT6 + 4096 MUXF7 + 2048 MUXF8），
   没算这部分。
2. **综合报告的 LUT 数不含 OOC IP。** 综合报告里 `xfft_0` / `blk_mem_gen_0` / `blk_mem_gen_1`
   被列为 **Black Box**，IP 自身的逻辑要到实现阶段才落实（实现后 Black Boxes 表为空）。
   所以**判断"布不布得下"必须看 `opt_design` 后/实现阶段的数**，
   综合数只能用来做"同一个东西前后对比"（这次 `19231 → 3702` 就是这个用法）。

> 顺带一个反向教训：我一开始看到"`RAMB18E1` 还是 4、没升到 6"差点误判成"`f_ram` 被优化掉了"。
> 真正的原因同样是 OOC 黑盒 —— **块 RAM 的增减要按"实例名 + 原语类型"去看，不能只数某一列的总数。**

#### 4.3.4 遗留的两条 Warning（如实记录，不影响本次使用）

| 规则 | 条数 | 含义 | 处理建议 |
|---|---|---|---|
| `REQP-1839` / `REQP-1840` | 20 + 20 | "RAMB36/RAMB18 async control check"：RAM 的地址脚由**带异步复位**的寄存器（`wr_idx` / `rd_idx` / FSM 状态）驱动，复位异步拉低时理论上可能读到/写到错值 | **Warning，不是错误**。写使能 `wr_en_w` 在复位时同时失效，实际风险低。若要彻底消除，需把 `wr_idx` / `rd_idx` 改成**同步复位** —— 但那会动到 FSM 时序，**本次不动**，列入后续清理项 |
| `CFGBVS-1` | 1 | 未在 XDC 里声明 `CFGBVS` / `CONFIG_VOLTAGE` | Warning，板子本来就能配置；后续可在 `wavecore.xdc` 里补两行说明 |

另有 `DPIP-1 / DPOP-1 / DPOP-2` 共 44 条 DSP 流水线建议 —— 纯性能/功耗建议，
本设计功耗只有 **0.149 W**（动态 0.077 W），**无需处理**。

---

## 5. 验证口径（别只看"综合过了"）—— 本次已全部通过 ✅

> **结论（2026-09-30 13:56）**：`Slice Registers 35818 → 2443`（综合口径）、
> `F7/F8 Muxes 4379/2180 → 11/4`，且 `f_ram_reg` 原语类型由 `FDRE` 变为 `RAMB36E1`。
> **三项判据全部命中，方案确认生效。** 下面保留判据表，供以后回归时复用。

改完重跑综合后，核对下面几个数，任一不符就是没生效：

| 检查项 | 期望 | 不达标说明 | 本次实测 |
|---|---|---|---|
| **`Slice Registers`** （最关键） | 从 35818 掉到 **3000 附近** | 还是 3 万多 = BRAM 推断又失败 | **2443 ✅** |
| **`F7 / F8 Muxes`** | 从 4379 / 2180 掉到 **300 / 130 附近** | 没掉 = 那个 4096:1 mux 还在 | **11 / 4 ✅** |
| **`f_ram` 的原语类型** | 出现 `RAMB36E1 u_fft_demo/f_ram_reg` | 若仍是 `f_ram_reg[x][y]/D ... FDRE` = 没生效 | **RAMB36E1 ✅** |
| ~~`RAMB18` 4 → 6~~ | ~~升到 6~~ | — | **这条判据是错的，已作废** |

> ⚠️ **`RAMB18` 那条判据是错的，已作废（保留在此以防以后又照抄）**：
> 综合报告里 `xfft_0` / `blk_mem_gen_0` / `blk_mem_gen_1` 是 **Black Box（OOC IP 不计入）**，
> 所以块 RAM 的数量在综合阶段本来就会少算，`RAMB18E1` 一直是 4。
> `f_ram` 实际落地为 **1 个 `RAMB36E1`**（4096 × 8 = 32 Kb，正好塞进一个 36 Kb 块）。
> **判断块 RAM 有没有进去，要按"实例名 + 原语类型"查，不能只数某一列的总数。**

**跑法**：`hw_analysis/sync_src_gbk.py`（仓库 UTF-8 → 工程 GBK）→
`rebuild_bitstream.bat` → 看 `wavecore.runs/synth_1/board_top_utilization_synth.rpt`
（`Slice Registers` 一结束就能看出来）；再对照 `impl_1/board_top_utilization_placed.rpt`
（这才是"含 IP 的完整设计"的真实占用）。

### 5.1 行为等价性回归（已备好，待本机跑）

`sim/fft_demo_check/`：用一个 `xfft_0` 行为级替身收下灌进 FFT 的样点并打滚动校验和，
对改动前后的 `fft_demo` 各跑一遍，逐字节比对。

```bash
cd wavecore/sim/fft_demo_check
bash run_equiv.sh          # 期望输出 PASS
```

激励用 8 位 LFSR（每个时钟都变）+ `DECIM=4` 抽点 —— **任何一处读地址差一拍，
4096 个抽点全会变，校验和立刻炸**，对地址偏移极度敏感。

> **诚实说明**：`xvlog`（编译）和 `xelab`（精化）在本机都已通过；
> 但 `xsim`（执行）在当前环境**无法运行** —— 连一个 `$display("HELLO")` 的最小设计
> 都在 90 秒内零输出挂死（关沙箱、`--nosignalhandlers`、`--nolog`、关 webtalk 都试过）。
> 这不是 testbench 的问题（最小设计同样挂）。**请在本机跑一次 `run_equiv.sh`。**

---

## 6. 备选与不推荐方案

### 6.1 备选（如果模板法没让 Vivado 松口）：直接换官方 IP

按 `skill/SK-016` 的结论：**别赌手写数组的推断，一步到位用 Block Memory Generator**。
本工程已经成功用过两次（`u_wave/u_bmg`、`u_scfft/u_mem`）。
生成一个 **4096 × 8、Simple Dual Port、读延迟 1** 的 BMG，把 `f_ram` 的读写口接到 IP 的
`addra/dina/wea` 和 `addrb/doutb`（`enb` 接 `rd_en_w`），其余照旧。
多花 3 分钟生成 IP，换 100% 确定性。

### 6.2 顺带可省但收益很小（**本次不需要**）

| 模块 | LUT | 说明 |
|---|---|---|
| u_meter / u_div | 744 / 235 | 减法循环除法器，已经是最省的写法 |
| u_report | 638 | 含新增的 `vpp_mv` 乘法器（已用 DSP） |
| u_mirror | 84 | F1 转发口在用，**不是死代码，别删** |

加起来才 1700，P0 做完根本用不上。**不要为了 29 个 LUT 去动这些。**

### 6.3 明确不推荐

- **`drc.disableLUTOverUtilError = 1`** —— 把错误降级成警告强行布局。
  竞赛提交作品，布线器在超容下会硬塞，时序和功能都可能出问题。**不要用。**
- **调 `opt_design` directive** —— `opt_design` 现在是净增 1598 个 LUT（为了时序优化做复制），
  调 directive 顶多省几百，治标不治本，而且可能牺牲时序。
- **删 `self_fft_1024`（u_scfft）** —— 它只占 502 LUT，却是 `0x8A / SF= 行`的全部来源，
  是作品的"自研算法"亮点。**为了 502 个 LUT 砍掉一个功能亮点，性价比极差。**

---

## 7. 一句话总结

> 设计不是"太复杂所以塞不下"，是**一个 32 Kb 的采样缓存退化成了 32768 个触发器**
> 外加一个 4096:1 的巨型多路器，一个人吃掉了全设计 86% 的 LUT 和 93% 的寄存器。
> 把它请回块 RAM，问题不是"缓解"，是**彻底消失**。

**实测（2026-09-30）**：改一行 RTL 风格（读口去异步复位 + 写读口各自独立 `always`），
`Slice LUTs 20829(100.14%，超容) → 5117(24.60%)`，`Slice Registers 35818(86.10%) → 4834(11.62%)`，
`place_design` 从报错中止变成 0 个布线错误、时序 WNS 反而从 +1.395 ns 放宽到 **+2.087 ns**。

> **真正的教训不在"块 RAM 怎么写"，而在"我改的那一个东西真的变了吗"**：
> 9/5 曾用"hann 改 ROM + 删另一块缓存"把总数降下来，掩盖了 `f_ram` 从未进 BRAM 的事实，
> 一藏 25 天。这次不再看总数，而是**直接去报告里查 `f_ram_reg` 的原语类型** ——
> 从 `FDRE` 变成 `RAMB36E1`，这才是能写进报告的闭环证据。
