# skill/ — 技能包（Skill）

> 赛题要求：把与大模型协作过程中沉淀的可复用经验提炼为技能包，占评分 15%。
> 评价标准是**可复用性**：一支陌生队伍拿到这个目录，能否直接用在自己的题目上。
> 每一条都要写明：适用场景、使用方法、失效条件，以及从哪些失败/观察中总结得出。

## 技能包格式模板

```markdown
## SK-xxx：技能名称（一句话）

- **适用场景**：什么时候用（什么条件下这个经验成立）
- **使用方法**：一步步怎么操作
- **失效条件**：什么时候这个方法不适用（边界要写清！）
- **来源**：从哪次失败/观察中总结的（日期 + 事件）
- **已验证效果**：用这个技能解决过什么问题
```

## 技能包清单

| 编号 | 名称 | 适用场景 | 状态 |
|------|------|----------|------|
| SK-001 | Vivado 中文注释乱码处理 | 代码含中文注释显示乱码 | 已录入 |
| SK-002 | 综合报 filemgmt 56-2 路径错误 | 工程路径含中文/在网盘目录 | 已录入 |
| SK-003 | 综合报 PID not specified | 工程在网盘同步目录/被杀毒干扰 | 已录入 |
| SK-004 | 仿真报 cannot open xxx.mem | $readmemh 找不到数据文件 | 已录入 |
| SK-005 | DRC BIVC-1 Bank 电压冲突 | 同 Bank IO 电平标准不一致 | 已录入 |
| SK-006 | ILA 改探针后新探针不显示 | 重配 ILA 后 P2 在硬件里看不到 | 已录入 |
| SK-005 | DRC BIVC-1 Bank 电压冲突 | 同一 Bank 的 IO 用了不同电平标准 | 已录入 |

## 已录入条目

## SK-001：Vivado 中文注释乱码处理

- **适用场景**：.v/.sv 代码文件含中文注释，Vivado 编辑器或综合/仿真时中文显示为乱码；或 GitHub 上中文乱码
- **使用方法**：
  1. 原理：代码文件是 UTF-8 编码，而 Vivado（2020.1 及常用旧版）按系统 GBK 读取 → 中文乱码
  2. 本地开发用文件：把 .v 代码转成 **GBK** 编码（VSCode 右下角点编码 → "通过编码重新打开/保存" → GBK；或用 Python 批量转）
  3. 文档类（.md/.txt）保持 UTF-8 不动
  4. 上传 GitHub 前，把 .v 转回 **UTF-8**（仓库统一 UTF-8，跨平台才不乱码）
- **失效条件**：注释纯英文时无需处理；含 emoji 等 UTF-8 独有字符的文件转 GBK 会失败或丢字符（先删掉再转）
- **来源**：团队前期研究踩坑（2026-09-02 录入）
- **已验证效果**：前期项目中出现并已用此法解决

## SK-002：综合报 filemgmt 56-2 路径错误

- **适用场景**：Vivado 综合/导入时报 `[filemgmt 56-2]` 类路径错误（文件找不到/路径无效），且工程所在路径含中文、空格或位于网盘下载目录
- **使用方法**：
  1. 把整个 Vivado 工程放到**纯英文本地路径**，例如 `D:/fpga/wavecore`（不要放桌面中文路径、不要放 `D:/Total download/夸克下载/...` 这类含中文的目录）
  2. 工程名、模块名也用纯英文
- **失效条件**：路径已全英文仍报错 → 不是路径问题，检查文件是否真被拷贝全、`.xpr` 里引用的源文件路径是否失效
- **来源**：团队前期研究踩坑（2026-09-02 录入）
- **已验证效果**：前期项目中出现并已用此法解决

## SK-003：综合报 PID not specified

- **适用场景**：综合（或运行）时报 `PID not specified` 类错误，工程在网盘同步目录（百度网盘/OneDrive 等）或被杀毒软件拦截
- **使用方法**：
  1. 把工程移出网盘同步目录（网盘会锁文件/拦截 Vivado 的临时进程）
  2. 关闭/白名单杀毒软件（尤其是刚装 Vivado 时的首次综合）
  3. 若上述都无效仍复现，考虑换更新版本 Vivado（2025.2 等）
- **失效条件**：工程本就不在网盘目录且无杀软干扰 → 查工程自身问题（缺文件、IP 核损坏等）
- **来源**：团队前期研究踩坑（2026-09-02 录入）
- **已验证效果**：前期项目中出现并已用此法解决

## SK-004：仿真报 cannot open xxx.mem（$readmemh 找不到文件）

- **适用场景**：仿真报 `cannot open sine_rom.mem` 或数据文件打不开——testbench 里用 `$readmemh("相对路径", mem)` 但 Vivado xsim 的工作目录不是工程根目录，相对路径失效
- **使用方法**：
  1. 把 .mem/.coe 数据文件复制到仿真运行目录：`<工程名>.sim/sim_1/behav/xsim/`（Vivado 2020.1 的 xsim 默认工作目录）
  2. 或干脆在 testbench 里写绝对路径（如 `$readmemh("D:/fpga/wavecore/sim/sine_rom.mem", ...)`）先跑通，再改相对路径
- **失效条件**：换用 Modelsim/Questa 等其他仿真器时工作目录不同，需按各自目录规则放置（xsim 的路径只对 xsim 有效）
- **来源**：团队前期研究踩坑（2026-09-02 录入）
- **已验证效果**：前期项目中出现并已用此法解决

## SK-005：DRC BIVC-1 Bank 电压冲突（同一 Bank 的 IO 电平标准必须一致）

- **适用场景**：实现阶段报 `[DRC BIVC-1] Bank IO standard Vcc: Conflicting Vcc voltages in bank XX`，例如 "sys_clk (LVCMOS15) 与 key0 (LVCMOS33) 冲突"
- **使用方法**：
  1. 原理：FPGA 引脚按 **Bank（电压域）**分组，同一 Bank 的所有引脚共用一个供电电压 VCCO，**同一 Bank 必须使用同一种电平标准**（LVCMOS15 配 1.5V、LVCMOS33 配 3.3V）
  2. 看报错信息里点名的两个端口 → 确定它们属于哪个 Bank、该 Bank 实际电压是多少
  3. **以官方例程 XDC 为准**：去资料盘找同类外设的官方约束，抄它的 IOSTANDARD，不要自己猜
  4. 达芬奇Pro 实例：sys_clk/sys_rst_n/key0~3/led0~3/beep/touch_key 全在 **bank34（1.5V 域）→ LVCMOS15**；AD/DA 模块与串口在 3.3V 域 → LVCMOS33
- **失效条件**：同一 Bank 内电平统一后仍报错 → 检查是否管脚号写错（把别的 Bank 的管脚误写进来）
- **来源**：WaveCore M3 真实踩坑（2026-09-03）：key0/led 误标 LVCMOS33 与 sys_clk 冲突，DRC 抓出后对照官方 XDC 修正为 LVCMOS15
- **已验证效果**：修正后 DRC 通过（用户回报 M3 实现成功前的一次真实排障）

## SK-005：DRC BIVC-1 Bank 电压冲突（同 Bank IO 电平标准必须一致）

- **适用场景**：实现阶段报 `[DRC BIVC-1] Bank IO standard Vcc: Conflicting Vcc voltages in bank xx`，例如"sys_clk (LVCMOS15) 与 key0 (LVCMOS33) 冲突"
- **使用方法**：
  1. 原理：FPGA 引脚按 **Bank** 分组，每个 Bank 有**同一个供电电压 VCCO**，同一 Bank 内所有 IO 必须用匹配该电压的电平标准（LVCMOS15 ↔ VCCO=1.5V、LVCMOS33 ↔ VCCO=3.3V），混用即报 BIVC-1
  2. 报错信息会直接告诉你哪两个端口冲突 → 把报错里提到的端口找出来
  3. **以官方例程 XDC 为准**：去资料盘找同类外设（按键/LED/串口/ADDA）的官方约束文件，抄它的 IOSTANDARD，不要凭感觉猜
  4. 达芬奇Pro 实例：sys_clk/sys_rst_n/key/led/beep/touch_key 全在 **bank34（1.5V 域）→ LVCMOS15**；AD/DA 模块（da_*/ad_*）与串口等在 **3.3V 域 → LVCMOS33**
- **失效条件**：若报错端口不在同一 Bank 却仍报 BIVC-1 → 检查 XDC 是否写错管脚号（管脚错位会把两个不同域的 IO 拉到一起）
- **来源**：WaveCore M3 真实踩坑（2026-09-03）：key0/LED 误标 LVCMOS33，DRC 抓出与 sys_clk 冲突；对照官方 XDC 修正为 LVCMOS15
- **已验证效果**：修正后 DRC 通过、布局布线正常

## SK-006：ILA 改探针后新探针（P2）在硬件里看不到

- **适用场景**：给 ila_0 加/改探针、重新生成 bit 并烧录后，ILA 波形窗口仍只有旧探针（如只有 P0/P1，没有新加的 P2/ad_cap）
- **使用方法**（按顺序排查，90% 是最后两条）：
  1. 确认 IP 真的改了：双击 ila_0 → Number of Probes / 宽度正确（最权威：看 `.xci` 里 `C_NUM_OF_PROBES`）
  2. 确认代码真的例化了新探针：`board_top.v` 里 `.probe2(ad_cap)` 存在
  3. 确认工程编译的是外部最新文件：Sources 里右键文件看路径，若在 `.srcs` 内=旧副本，Remove 后重新 Add
  4. 改 IP 后必须整套重跑：Synthesis → Implementation → Generate Bitstream（改了 IP 四步缺一不可）
  5. 烧录时**确认选的是最新 bit**：Program Device → Browse → 看文件修改时间（老 bit 没有新探针，这是最常见原因）
  6. 烧完看 **hw_ila 核的探针清单**（不是波形窗口）：展开 hw_ila_1，若清单里有 P2 而波形里没有 → 在波形窗口右键 **Add/Remove Signals** 勾选 P2（波形不会自动显示新探针！）
  7. 硬件核编号 hw_ila_1/hw_ila_2 是 Vivado 按顺序起的，**与 IP 名 ila_0 无关**，别被误导
- **失效条件**：若探针清单里始终只有旧探针 → 用 `reset_and_build.tcl`（reset 全部 run 强制无缓存重建）排除 OOC 缓存
- **来源**：WaveCore M4a 真实踩坑（2026-09-03），排查链：IP 配置→代码→工程引用→缓存→烧录文件→波形显示
- **已验证效果**：最终在波形窗口手动添加 P2(ad_cap) 后显示正常

## 怎么积累

1. 每次遇到 bug / 卡壳 → 解决后 10 分钟内写一条（趁热）
2. 每条控制在 5~10 行，能让人"照着做就能避开坑"
3. 写不清"失效条件"的技能包不算合格
4. 每月底整理一次，删除过时条目

## 候选素材（已想到的，等踩坑后补充细节）

- 下载器 / JTAG 连不上达芬奇 Pro 的排查顺序
- Vivado 2020.1 建工程必改的设置（如器件选型、语言版本）
- Verilog 仿真与综合行为不一致的常见原因
- 时序违例（WNS 为负）的排查流程
- 表格文件（xlsx）解析通道不可用时的本地降级流程（openpyxl 直读）
- wire vs reg：`always` 块里赋值的信号必须是 reg（报 Synth 8-2576 / procedural assignment to a non-register）
- 复杂发送状态机先化简（固定宽度报文/单指针/单 always），别硬堆状态
