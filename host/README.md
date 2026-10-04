# WaveCore Python上位机

本目录是WaveCore的电脑端上位机，用于连接FPGA板卡、显示测量结果、控制DDS信号源，并查看波形、频谱和瀑布图。当前代码按串口协议 **v1.20** 开发。

> 状态（2026-10-04）：主GUI的v1.20适配代码已接入，**尚待运行和上板回归验证**；独立工具 `spectrum_waterfall.py` 已于2026-10-01上板验证通过。

## 功能

- 自动识别CH340串口，460800-8N1连接(v1.8 提速)。
- 实时显示测量频率F、Vpp毫伏值、FFT主峰S和第二峰A。
- 显示占空比D、脉宽W、波形自动识别TY和自研FFT三峰SF/S2/S3。
- “控制状态”只记录最近成功发送的设置；TY是FPGA独立识别结果，不能反向覆盖已应用波形。
- 发送0x85设置1～12500000 Hz主频。
- 发送0x87开启第二频率，支持双音测试。
- 发送0x81切换100 kHz、200 kHz、500 kHz和1 MHz预设档位。
- 发送0x88切换正弦、方波和三角波，发送0x89选择自由、上升沿或下降沿触发。
- 发送0x8A运行一次自研FFT，发送0x8B开始或停止1～20 kHz扫频。
- 发送0x8C设置Vpp标定系数；原始模式自动把显示单位切换为LSB。
- 发送0x8D切换T1～T4时基（12.5/50/100/200 kHz），波形时间轴和频谱轴同步变化。
- 发送0x83请求1024点波形，支持500ms/1s/2s自动刷新、触发点标记和5点中值滤波显示。
- 发送0x8E连续请求512点幅度谱，在主GUI显示当前频谱和120帧瀑布图。
- 测量结果记录为CSV，最多10行/秒。
- 导出当前1024点原始波形CSV和512点频谱CSV。
- 串口断开后每1秒尝试重连，COM号变化时重新寻找唯一的CH340设备；连接成功后重新同步当前时基和Vpp标定系数。
- 同时兼容新固件的 `\r\n` 和旧固件的 `\r` 行尾。

## 运行环境

- Python 3.13（其他近期Python 3版本也可尝试）
- pyserial 3.5
- matplotlib 3.11
- tkinter 8.6（Windows Python安装程序通常自带）

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 连接

1. 断电时插好AD/DA模块和DA→AD回环线。
2. 给FPGA板卡上电并打开开关。
3. 用USB连接板载CH340和电脑。
4. 确认Windows设备管理器出现 `USB-SERIAL CH340 (COMx)`。
5. 关闭XCOM、串口助手及其他占用该COM口的程序。

## 启动

```powershell
cd wavecore_real-main\host
python wavecore_gui.py
```

界面打开后选择COM口并点击“连接”。

## 推荐演示流程

1. 主频输入 `1000`，点击“设置主频”。
2. 确认F约为1000 Hz，S约为1001 Hz。
3. 点击“请求1024点波形”，确认显示约20个正弦周期。
4. 第二频率输入 `1100`，点击“开启双音”。
5. 确认S/A中出现约1001 Hz和1099 Hz两个谱峰。
6. 点击“恢复单音”，第二峰恢复为 `-- Hz`。

双音时F受拍频影响会波动，S/A的主次顺序也可能交换，均为正常现象。

## CSV文件

实时测量CSV列：

```text
timestamp,frequency_hz,vpp_value,vpp_unit,vpp_kn,peak_s_hz,peak_a_hz,duty_percent,pulse_width_us,waveform_type,self_fft_peak_1_hz,self_fft_peak_2_hz,self_fft_peak_3_hz
```

波形CSV列：

```text
sample_index,time_ms,adc_lsb
```

频谱CSV列：

```text
timebase,sample_rate_hz,bin,frequency_hz,magnitude_code,relative_db_approx
```

频谱的 `relative_db_approx` 以本帧最大幅度码为0 dB，只用于展示相对结构。

单音没有第二峰时，`peak_a_hz` 留空。
Vpp通常以毫伏(mV)显示；选择“原始LSB模式”(KN=1024)时，界面和CSV都明确改用LSB。
换算 `mV = Vpp_LSB × KN ÷ 1024`，`KN` 由 0x8C 命令设定，默认 8000 = 7.8125 mV/LSB。
**默认 KN 只是「按 0~2V 量程」的假设值**，要当电压表用得先按 `board/uart_protocol.md` §2.8 标定。

## 独立审计脚本（check_duty.py）

对照板子输出与电脑自算结果（打印波形幅度、前/后6点、占空比、最长高/低电平）：

```
python check_duty.py COM5            # 默认 460800
python check_duty.py COM5 115200     # 旧固件兼容
```

- 触发验证：上升沿触发后"前6点"应为全高；下降沿应为全低
- "前6点"是触发/对齐类调试的关键读数

## 调试脚本

协议自检：

```powershell
python protocol.py
```

终端串口测试：

```powershell
python serial_test.py COM4 1000
python serial_test.py COM4 1000 1100
python serial_test.py COM4 1000 --wave
```

完整硬件冒烟测试：

```powershell
python hardware_smoke_test.py COM4
```

## 主GUI v1.20回归清单（代码完成后必须逐项实测）

测试前关闭XCOM、串口助手和独立 `spectrum_waterfall.py`，保证只有主GUI占用COM口。

1. **离线协议自检**
   - 运行 `python protocol.py`。
   - 应显示“协议自检全部通过”；覆盖0x8D四档命令、0x8E请求、512点谱帧、分段收帧、T4波形采样率和错误校验和拒收。
2. **连接与基础测量**
   - 打开GUI连接CH340，状态应显示460800和已同步T1。
   - 设1kHz正弦，确认F约1000Hz、Vpp单位为mV、S约1001Hz、TY=1。
3. **波形与自动刷新**
   - 请求波形，应看到约20个正弦周期。
   - 分别选择500ms、1s、2s自动刷新，确认持续更新且显示合理fps。
   - 勾选5点中值滤波，只允许显示曲线变化；导出的波形CSV必须仍是原始样点。
   - 信息栏必须同时显示“原始波形Vpp（LSB）”与“FPGA测量Vpp（mV）”。
4. **触发标记**
   - 切上升沿/下降沿后请求波形，图中应出现红色 `触发点 t=0` 标记。
5. **双音状态**
   - 开启1kHz+1.1kHz双音，S/A应约为1001/1099Hz，D/W必须显示 `--（双音）`。
   - 改频率、波形、单双音、扫频或时基后，旧SF/S2/S3必须立即清空，禁止把上一轮自研FFT结果当成当前结果。
   - 恢复单音后D/W应重新更新。
6. **实时频谱与瀑布**
   - 设1kHz方波，开始实时频谱：应连续收到512点谱帧，并看到1k/3k/5kHz谱柱。
   - 开始扫频：瀑布图应出现循环斜线；停止扫频后恢复静态谱柱。
7. **四档时基**
   - T1：fs=50kHz，范围0～25kHz，1k/3k/5k约落bin 20/61/102。
   - T2：fs=12.5kHz，范围0～6.25kHz，约落bin 82/246/410。
   - T3：fs=100kHz，范围0～50kHz，约落bin 10/31/51。
   - T4：fs=200kHz，范围0～100kHz，约落bin 5/15/26。
   - 每次切档后，波形时间轴、频谱横轴和Δf必须同时变化，旧波形和旧瀑布必须清空；收到新帧前不得把旧样点套用到新时基。
8. **CSV导出**
   - 测量CSV必须同时写入`vpp_value`、`vpp_unit`和`vpp_kn`；原始模式不得把LSB误标成mV。
   - 波形CSV应为1024个原始样点，时间步长按当前时基计算。
   - 频谱CSV应为512行数据，包含时基、fs、bin、频率、幅度码和近似相对dB。
9. **断线重连**
   - 保持T2/T3/T4任一档位及任一KN，拔掉USB再插回；3秒内应自动重连并重新发送当前0x8D档位和0x8C标定值。

以上全部通过后，才能把主GUI状态从“代码已接入”改成“v1.20已上板验证”。

## 常见问题

- `PermissionError` 或“Access denied”：其他程序占用了串口。
- 看不到COM口：检查USB线、板卡电源和CH340驱动。
- F正常而S异常：看波形和FFT时将信号设为20 kHz以下。
- 中文终端乱码：先执行 `chcp 65001`。
- 波形请求失败：确认固件支持0x83，并关闭其他串口程序。
- 脚本"秒退无输出"：检查脚本文件是否被写坏成 0 字节（用 dir 看大小）。
- 固件 **v1.20** 的 D/W、TY、SF/S2/S3、0x88～0x8E 已接入主GUI代码；`V=` 为4位mV。
- 主GUI新增频谱/瀑布、四档时基、波形自动刷新、中值滤波显示及频谱CSV，**完成运行回归前不得标为主GUI已验收**。
- 独立工具的一键入口仍保留：`run_waterfall_1k_sq.bat`、`run_waterfall_1k_sin.bat`、
  `run_waterfall_sweep.bat`、`run_waterfall_T2.bat`、`run_waterfall_T3.bat`、`run_waterfall_T4.bat`。

## link_response_scan.py —— 模拟链路频响实测（2026-09-28 新增）

回答"我们的可观察带宽有多高"，用来决定**时基档位（fs）的上限依据**。

```bash
python link_response_scan.py            # 自动找 CH340 串口
python link_response_scan.py --port COM4 --no-plot
```

- 原理：DDS 输出固定幅度正弦，频率 100Hz→1MHz 扫描，读 FPGA 上报的 Vpp，画"频率-幅度"曲线
- **可信原因**：测量通路吃的是 25MSPS 的 ADC 流，不受"波形 50kHz 抽取"影响 → 反映**真实模拟带宽**
- 输出：`link_response.csv`（频率/Vpp 中位数/范围/实测频率/波形类型）+ `link_response.png`（matplotlib 可用时）
- 自动给出 **-3dB 可用带宽** 与建议的最高 fs 档位（≥2.5 倍可用带宽）
- **[10-01] 扫频点在 25k~100 kHz 加密**（20→25→30→40→50→60→80→100 kHz）：这段正是时基 **T4 档（fs=200 kHz）
  新增覆盖**的范围 —— 这条曲线的 -3dB 位置，直接决定 T4 是"真扩容"还是"只多了一段噪声"

## spectrum_waterfall.py —— 0x8E 频谱图 / 瀑布图小工具（2026-09-30 新增）

独立频谱展示和诊断工具；主GUI现已接入同一0x8E数据源，但在主GUI完成回归前，本工具仍可作为已验证的演示兜底。

```bash
# 双击（推荐）：
run_waterfall.bat            # 只有一个串口时自动选择
run_waterfall.bat COM5
# 或命令行：
python spectrum_waterfall.py COM5 --interval 0.15
python spectrum_waterfall.py --demo            # 无板演示（合成扫频数据）
python spectrum_waterfall.py --demo --save x.png   # 自测出图
```

- 原理：每 `interval` 秒发一条 `0x8E`（`5A A5 8E 00 00 8E`）→ 收 518B 谱帧 → 上图画频谱 + 瀑布
- 上图 = 当前频谱（0~25kHz，512 点，对数压缩码）；下图 = 瀑布（历史滚动，**扫频时是一条斜线**）
- 用**系统 Python 3.8**（pyserial/matplotlib/numpy 都装好；`run_waterfall.bat` 里写死了绝对路径）
- 演示用预览图：`preview_waterfall_demo.png`（合成数据出的效果图）

## check_interp.py —— 频谱插值板测 / 一键判读（2026-10-01 新增）

验证**抛物线插值**（自研 FFT 通路的 `USE_INTERP`）有没有真的进这块板子的固件。

```bash
run_check_interp.bat                          # 双击（推荐）：自动选口 + 自动发帧 + 自动判读
run_check_interp.bat COM5                     # 指定串口
run_check_interp.bat COM5 --wave 0 --secs 8   # 换正弦 / 多读一会儿
```

- 动作：自动依次发 `停扫频(0x8B) → 设 1000Hz(0x85) → 方波(0x88) → 运行自研FFT(0x8A)`，
  再周期性重触发，读回 `F/V`、`S/A`、`SF/S2/S3` 等文本行
- **直接给判定**（1kHz 方波，T1 默认）：`SF` 990~1010 → 插值生效（旧行为是 **976**）；
  `S2` 2990~3006（旧 2978）；`S3` 4990~5006（旧 4980）；中间地带会提示"把原始行发我"
- 期望值来源：`hw_analysis/probe_interp.py`（数值模型，与 RTL 同口径）
- **实测（2026-10-01 12:1x，COM5，1kHz 方波）**：`SF=999` / `S2=2998` / `S3=4997` —— 三项 PASS，
  与模型 999.4 / 2998.4 / 4997.8 **逐字吻合**；IP 通路对照 `S=1001` 未受影响
- 为什么单独做个工具：`0x8A/0x8B/0x8D` 都是**静默命令（无 ACK）**，只能靠"读数落在哪个区间"反推生效与否
- 依赖：只用 pyserial，**不需要 matplotlib / numpy** —— 所以比瀑布图工具更轻、更快

## make_frames.py —— 命令帧生成 + 校验和自复核（2026-09-30 新增）

按项目约定：**凡是要设信号（频率/波形/触发/抓波形），必须附上可粘贴的 HEX 帧**。
本脚本就是那个"随手要帧"的入口，生成完还会**反向重算一遍校验和**自证。

```bash
python make_frames.py
```

输出：18 条常用帧（设 100Hz/1000Hz/2k/5k/10k/20k/37.5kHz、预设三档、波形三选、触发三档、
请求波形、自研 FFT、**幅度谱帧请求(0x8E)**、扫频开关、第二频率），格式 `5A A5 TYPE LEN_H LEN_L PAYLOAD SUM`，
**波特率 460800-8N1**。

> 它是"生成器"；`hw_analysis/check_protocol_frames.py` 是"审计器"——
> 后者会把 `board/uart_protocol.md` 里**所有**帧抠出来逐条复核长度与校验和。
> 改过协议表后请跑一次审计器（2026-09-30 就是它抓出 37.5kHz 那行的小端字节写错）。

### 烧板后的复验步骤

见 **`board/verify_checklist.md`**（带全部可粘贴帧）。最关键的一条：
**上电默认是 100kHz 预设档，而自研 FFT 的 fs 只有 50kHz —— 必须先显式发"设 1000Hz"**，
否则 100kHz 会混叠，`SF` 永远出不来 976。
