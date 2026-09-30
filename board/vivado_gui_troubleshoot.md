# Vivado 2020.2 GUI 崩溃排查手册

> 起因：2026-09-30 09:34 打开工程时 Vivado 直接崩了（`java.lang.NullPointerException`），
> `open_project` 报 `ERROR: [Vivado 12-106] *** Exception`，**工程根本打不开**。
> 本文记录定性结论、证据和绕行方案。
> 相关脚本：`program_device.tcl/.bat`、`rebuild_bitstream.tcl/.bat`

---

## 一、结论先说

| 问题 | 结论 |
|---|---|
| 是不是我的工程/代码坏了？ | **不是**。`.xpr` 是合法 XML，能正常解析；**2026-09-30 09:30 那次会话 16 秒就正常打开了工程** |
| 是不是我 9/28 改的 RTL / GBK 编码搞的？ | **不是**。同一个崩溃栈在 **2026-09-20** 就出现过一次（证据：`%APPDATA%\Xilinx\Vivado\vivado_pid19572.zip`），栈帧逐行相同 |
| 那是什么？ | **Vivado 2020.2 自带的 GUI bug**：往"语法高亮文本框"(JIDE `CodeEditor`) 里插入文本时，`TreeMap` 抛 NPE。触发点在 `open_project` 期间 GUI 还原视图的时候 |
| 比特流还在吗？需要重跑综合吗？ | **在，不需要**。见下方"三、已确认的好消息" |

---

## 二、崩溃技术细节（留证）

**崩溃文件**：`%APPDATA%\Xilinx\Vivado\vivado_pid21700.zip`（内含 `.debug` 栈 + `vivado.xml` + 日志）

**关键栈帧（自下往上 = 触发顺序）**：

```
BasicListUI$Handler.mouseReleased                     <- 鼠标在列表上松开
  -> ui.views.q.j.valueChanged(488)                   <- JList 选中项变化
  -> ui.dlg.c.bI.actionPerformed(1182)                <- 对话框按钮动作
  -> ui.dlg.c.g.setVisible(864)                       <- 对话框显示
  -> ui.PlanAhead.handleTclEvent(1687)                <- 走 Tcl 事件构建视图
  -> ui.views.Q.u.kdf(981) -> ui.views.m.D.<init>     <- 建"文本视图"
  -> ui.data.experiment.S.<init>(107)                 <- 组装要显示的文本
  -> ui.views.m.p.print(64)                           <- 往编辑器里 append 文本
  -> com.jidesoft.editor.CodeEditor.append
  -> com.jidesoft.editor.SyntaxDocument.insertString
  -> ui.h.c.f.insertUpdate(81) -> f.c(192) -> f.d(213)
  -> java.util.TreeMap.put -> TreeMap.fixAfterInsertion  <<< NullPointerException
```

**日志时间线**：

```
09:30:34  PID 504    open_project 成功(16s)
                     open_hw_manager -> connect_hw_server 失败 x2
                     ERROR: [Labtools 27-3733] cs_server 无法连到 hw_server @TCP:3121
09:33:57  退出
09:34:00  PID 21700  open_project -> Finished scanning sources
                     -> Loaded Vivado IP repository
                     -> ERROR: [Vivado 12-106] Exception: java.lang.NullPointerException
                     -> ERROR: [Common 17-39] 'open_project' failed
09:35:54  退出（崩溃）
```

**历史崩溃次数**（`%APPDATA%\Xilinx\Vivado\` 下）：`hs_err_pid39356.log`(9/5，JVM 原生崩溃)、
`vivado_pid19572.zip`(9/20)、`vivado_pid5720.zip`(9/20)、`vivado_pid4980.str`(9/16)、
`vivado_pid5060.str`(9/20)、`vivado_pid21700.zip`(9/30)。
**这是个反复出问题的安装环境，不是偶发。**

---

## 三、已确认的好消息：新固件早就编译好了

上次会话（9/29 晚上）的重新综合+实现**已经成功**，而且用的就是修过 FFT 输入映射的源码：

| 项目 | 值 |
|---|---|
| 源文件 `src/self_fft_1024.v`（含修复） | 2026-09-28 08:58 |
| `synth_1/board_top.dcp` | 2026-09-29 22:00 |
| **`impl_1/board_top.bit`（2.19 MB）** | **2026-09-29 22:20** |
| 时序 | **WNS = +1.395 ns，TNS = 0.000；WHS = +0.064 ns，THS = 0.000** → 建立/保持全收敛 |
| `write_bitstream` | `Bitgen Completed Successfully` / `completed successfully` |

**所以现在唯一缺的一步就是"把这份 bit 烧进板子"。**

---

## 四、怎么办：三条路线（按推荐顺序）

### 路线 1（推荐）：不开 GUI，直接烧板

双击 **`program_device.bat`**（工程根目录）。它做三件事：
1. 先 `taskkill` 掉可能残留的 `hw_server.exe` / `cs_server.exe`
   —— 这正是 09:30 那次 `cs_server 无法连到 hw_server` 的原因（残留进程占住 3121/3042 端口）；
2. 用 `vivado -mode batch` 跑 `program_device.tcl`（**全程不进 GUI，绕开那个崩溃**）；
3. 烧完打印提示。

> `program_device.tcl` 里**没有 `open_project`** —— 烧板只需要硬件管理器，不需要工程。

**烧完怎么复验这次修复生效**（串口 **460800-8N1**，三条按顺序发）：

```
5A A5 85 00 04 E8 03 00 00 74      设 1000Hz        <<< 这条不能省!
5A A5 88 00 01 00 89               波形=正弦
5A A5 8A 00 01 00 8B               自研 FFT 运行一次
```

期望：`SF=0000976Hz` / `S2=0000000Hz` / `S3=0000000Hz`。
**若 S2/S3 不是 0，说明烧进去的还是旧固件**（旧版会把正弦造出假谐波）。

> ⚠️ **"设 1000Hz" 不能省**：`freq_ctrl.v` 复位后默认是 **100kHz 预设档**，
> 而自研 FFT 的 fs 只有 50kHz —— 100kHz 会直接混叠，`SF` 不可能出 976。
> 完整复验清单（含方波对照、异常对照表）见 **`board/verify_checklist.md`**。

### 路线 2：需要重新综合时，同样不开 GUI

双击 **`rebuild_bitstream.bat`** → 命令行跑 `reset_run + launch_runs impl_1 -to_step write_bitstream` + 出 `timing_summary.rpt`。
约 8~15 分钟（LUT 95%，实现吃时间）。

### 路线 3：还想用 GUI（只在路线 1/2 不可用时）

按"从小到大"试，每步之后重开一次 Vivado：

1. **关掉所有 Vivado，重开，用 `File → Open Project` 手选 `.xpr`，不要点"最近工程列表"。**
   依据：崩溃栈是从"列表选中项变化"进来的。
2. 若仍崩：把 `%APPDATA%\Xilinx\Vivado\2020.2\vivado.xml` **改名成 `vivado.xml.bak`**
   （只丢窗口布局和最近文件列表，不影响工程），重启 Vivado 让它重建默认配置。
3. 若仍崩：删除工程下可再生的缓存目录 `wavecore.cache/`、`wavecore.gen/`、`wavecore.hw/`、
   `wavecore.ip_user_files/`（**不要删 `.srcs/`、`.runs/`、`.xpr`、`src/`**），重启后 Vivado 会重建。

---

## 五、已知坑速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `open_project` 报 `Vivado 12-106 Exception: NullPointerException` | GUI 文本框 NPE（本文） | 走路线 1/2；或路线 3 |
| `[Labtools 27-3733] cs_server 无法连到 hw_server @TCP:3121` | 上次会话残留 `hw_server.exe`/`cs_server.exe` 占端口 | `taskkill /F /IM hw_server.exe`、`taskkill /F /IM cs_server.exe`；端口 3121/3042 空出来再连 |
| `connect_hw_server` 失败 | 同上，或 USB/驱动/板子没上电 | 见上；换 USB 口；CI 下可用 `-allow_non_jtag` |
| 命令行 `vivado -mode batch` 卡住不动 | 可能是上一个被强杀的实例留下的锁 / 无控制台时弹了隐藏对话框 | 先 `taskkill` 掉所有 `vivado.exe` 再重试；双击 `.bat`（有控制台）比在无终端环境里跑更稳 |
| `ERROR: [Common 17-39] xxx failed due to earlier errors.` | 通常是**前面那一条**真错误导致的连锁 | 往前翻日志找第一个 `ERROR`，别盯最后一条 |

> **纪律**：强杀过 Vivado（或它崩过）之后，动手前先在任务管理器里确认
> **`vivado.exe` / `hw_server.exe` / `cs_server.exe` 一个都不剩**，否则下一步大概率还是失败。

---

## 六、命令行 XSim 无输出挂死（2026-09-30 记录）

### 现象
```
xsim tb_unit -R          # 无任何输出，挂住，零字节日志
xsim tb_unit -tclbatch run.tcl    # 同样挂
xsim tb_unit -R < /dev/null       # 同样挂
```
`xsim --version` 正常打印版本；`xvlog` / `xelab` 全部正常完成。

### 关键判据（怎么确定不是自己代码的问题）
**把 09-28 已经跑通过、有完整 PASS 日志的旧快照拿出来重跑，一样挂。**
旧快照 `sim/fft_check/tb_sim` 的日志末尾还留着
`RESULT: PASS=4  FAIL=0 / $finish called at 5736010 ns`，
而现在同一目录同一命令 `timeout 60 xsim tb_sim -R` → `EXIT=124`（超时）、日志 0 字节。

→ **结论：xsim 的运行阶段在当前会话环境里起不来，与被测 RTL/测试平台无关。**

### 怎么办
| 想做的事 | 现在能用的办法 |
|---|---|
| 验语法 / 端口连接 / 模块是否齐全 | `xvlog` + `xelab` **照常可用**（本次就靠它确认 3 个 tb 全部编译+精化通过） |
| 真的要跑波形看数值 | 把 `sim/*/tb_*.v` 加进 Vivado 工程，用 GUI 的 **Run Simulation**（GUI 若崩见 §四 路线 3） |
| 纯算法/数值的验证 | 另写一份 Python 复算（如 `sim/mv_check/oracle.py`），用独立语言交叉核对 |

### 纪律
- **不要**因为"跑不了就跳过"，也不要让脚本"失败但静默通过"。
  `sim/mv_check/run_mv_check.sh` 已改成：编译/精化失败即停，运行阶段失败**明确告警并返回非零**，不假装成功。
- 交付/答辩时**不能**把"只过了 xvlog/xelab"说成"仿真通过"。二者严格性差一个量级：
  前者只证明"写得合法"，后者才证明"算得对"。
