# -*- coding: utf-8 -*-
"""
WaveCore串口协议模块

负责：
1. 生成协议命令帧（0x81、0x83、0x85、0x87～**0x8F**；**v1.17 起 `V=` 是 4 位 mV**；
   **v1.20 起含 0x8D 时基四档 / 0x8E 幅度谱帧；v1.21 起含 0x8F 预触发比例**）
2. 解析F/V、S/A、D/W、TY、SF/S2/S3文本行
3. 解析1024点波形帧和512点幅度谱帧

v1.17 变更(2026-09-30, **文本行有破坏性改动**):
  - `V=` 字段由 3 位 ADC 计数(LSB) 改成 **4 位毫伏(mV)**: `F=0001000Hz V=1085`
  - 配套新增 0x8C 电压标定命令
  - 解析结果里的键名 `vpp_lsb` -> `vpp_mv`(单位变了, 名字必须跟着变, 否则会静默算错)

v1.20 变更(2026-10-01):
  - 0x8D 选择时基，等效采样率 12.5k～200kHz
    **⚠️ 2026-10-14 上位机只开放 T1(50k) / T2(12.5k)**；T3/T4 已屏蔽，见 TIMEBASE_SAMPLE_RATES
  - 0x8E 请求512点8bit对数压缩幅度谱帧
"""

import re


FRAME_HEADER = b"\x5A\xA5"

# ============================================================================
# [0x8D 时基档位 -> 等效采样率 Hz]   ★ 单一事实源，勿在别处重复定义
#
#   [2026-10-14 收窄] 演示/提交只保留 **T1(50k) 与 T2(12.5k)** 两档。
#     原因：T3(100k)/T4(200k) 在实机切换后无响应，根因未定位
#           （见 report/t3t4_disable_2026-10-14.md）。
#     ★ **FPGA 侧四档仍然完整**，这里只是把上位机的"入口"撤了 ——
#       固件、时基模块、文档里的四档描述都不受影响。
#
#   [恢复办法] 把下面两行注释去掉，并同步恢复：
#       wavecore_gui.TIMEBASE_CHOICES     加回 T3/T4
#       spectrum_waterfall.TB_FS          加回 2/3
#       host/run_waterfall_T3.bat / T4.bat（已删，可在 git 里找回）
# ============================================================================
TIMEBASE_SAMPLE_RATES = {
    0: 50_000,      # T1 默认（上电即此档）
    1: 12_500,      # T2 细分辨率 Δf = 12.2 Hz
    # 2: 100_000,   # T3 —— 2026-10-14 上位机屏蔽
    # 3: 200_000,   # T4 —— 2026-10-14 上位机屏蔽
}

MEASUREMENT_PATTERN = re.compile(
    rb"^F=(\d{7})Hz V=(\d{4})$"
)

PEAK_PATTERN = re.compile(
    rb"^([SA])=(\d{7})$"
)

DUTY_PATTERN = re.compile(
    rb"^D=(\d{3}\.\d)% W=(\d{5})us$"
)

WAVEFORM_TYPE_PATTERN = re.compile(
    rb"^TY=([0-3])$"
)

SELF_FFT_PATTERN = re.compile(
    rb"^(SF|S2|S3)=(\d{7})Hz$"
)


def build_command(command_type: int, payload: bytes = b"") -> bytes:
    """生成通用下行命令帧。"""
    if not 0 <= command_type <= 0xFF:
        raise ValueError("命令类型必须在0x00～0xFF之间")

    if len(payload) > 0xFFFF:
        raise ValueError("负载过长")

    body = (
        bytes([command_type])
        + len(payload).to_bytes(2, "big")
        + payload
    )

    checksum = sum(body) & 0xFF

    return FRAME_HEADER + body + bytes([checksum])


def command_set_preset(index: int) -> bytes:
    """
    生成0x81预设档位命令。

    0 = 100kHz
    1 = 200kHz
    2 = 500kHz
    3 = 1MHz
    """
    if index not in (0, 1, 2, 3):
        raise ValueError("档位必须是0、1、2或3")

    return build_command(0x81, bytes([index]))


def command_request_waveform() -> bytes:
    """生成0x83波形请求命令。负载0x00为保留占位符。"""
    return build_command(0x83, b"\x00")


def command_set_frequency(hz: int) -> bytes:
    """生成0x85主频设置命令。"""
    if not 1 <= hz <= 12_500_000:
        raise ValueError("主频必须在1～12500000 Hz之间")

    payload = hz.to_bytes(4, "little")
    return build_command(0x85, payload)


def command_set_second_frequency(hz: int) -> bytes:
    """生成0x87第二频率设置命令。"""
    if not 1 <= hz <= 12_500_000:
        raise ValueError("第二频率必须在1～12500000 Hz之间")

    payload = hz.to_bytes(4, "little")
    return build_command(0x87, payload)


def command_set_waveform(waveform_type: int) -> bytes:
    """生成0x88波形选择命令：0=正弦，1=方波，2=三角。"""
    if waveform_type not in (0, 1, 2):
        raise ValueError("波形类型必须是0、1或2")
    return build_command(0x88, bytes([waveform_type]))


def command_set_trigger(trigger_mode: int) -> bytes:
    """生成0x89触发模式命令：0=自由，1=上升沿，2=下降沿。"""
    if trigger_mode not in (0, 1, 2):
        raise ValueError("触发模式必须是0、1或2")
    return build_command(0x89, bytes([trigger_mode]))


def command_run_self_fft() -> bytes:
    """生成0x8A自研FFT运行一次命令。"""
    return build_command(0x8A, b"\x00")


def command_set_sweep(enabled: bool) -> bytes:
    """生成0x8B扫频开关命令。"""
    return build_command(0x8B, bytes([1 if enabled else 0]))


# Vpp 标定的默认值: 36.33 mV/LSB x1024（2026-10-02 实测标定并固化）
DEFAULT_VPP_KN = 37203
# 把 KN 设成这个值, 上报的 V 字段就是**原始 ADC 计数** (1024>>10 = 1)
RAW_LSB_KN = 1024


def command_set_vpp_cal(kn: int = DEFAULT_VPP_KN) -> bytes:
    """
    生成0x8C电压标定命令。

    kn = 每 LSB 对应多少 mV, 放大 1024 倍取整(Q10定标)。
      - 默认 37203 -> 36.33 mV/LSB, 对应模块输入端的 ±5V 量程（2026-10-02 实测标定）
      - 传 1024    -> "原始 LSB 透传模式", 上报的 V 就是 ADC 计数, 专供标定用

    标定流程(两点法):
      1. 发 command_set_vpp_cal(RAW_LSB_KN), 记下 V 字段的原始计数 N
      2. 用万用表量出真实峰峰值 V_true (mV)
      3. 发 command_set_vpp_cal(round(V_true * 1024 / N))
    """
    if not 0 <= kn <= 0xFFFF:
        raise ValueError("kn 必须在 0～65535 之间")
    return build_command(0x8C, kn.to_bytes(2, "little") + b"\x00\x00")


# ============================================================================
# [0x8D 时基档位]（协议 v1.19 新增三档；v1.20 加 T4）
#   档位的等效采样率见文件上方的 TIMEBASE_SAMPLE_RATES（单一事实源，勿重复定义）
#   切换会同时改变：波形帧窗长 / 自研 FFT 的 Δf / IP FFT 窗长 / 频谱覆盖
#   1024 点自研 FFT 的 Δf：T1 48.8Hz / T2 12.2Hz / (T3 97.7Hz / T4 195.3Hz 已屏蔽)
#
#   ⚠️ 2026-10-14：**上位机只开放 T1/T2**（T3/T4 实机无响应，根因未定位）。
#      本函数对已屏蔽档位会直接抛 ValueError —— 这是刻意的，"发得出去但不生效"
#      比"当场报错"更难排查。
# ============================================================================


def command_set_timebase(tier: int) -> bytes:
    """
    生成 0x8D 时基档位命令（协议 v1.20）。

    tier: 目前开放 0=T1 50kHz(默认) / 1=T2 12.5kHz
          （2=T3 100kHz / 3=T4 200kHz 已由上位机屏蔽，见 2026-10-14 说明）

    ⚠️ **0x8D 是静默命令（没有 ACK / 回执行）** —— "发过去没反应"是**正常**的。
       只能靠可观察量判断生效：同一个 1kHz 方波，自研谱峰 bin 号会变
       （T1 bin20 / T2 bin82），波形帧里的周期数也会变（20 / 82）。

    ⚠️ 上位机必须**自己记住当前档位**：0x8E 谱帧本身不带 fs，
       否则频率轴会标错（用 `timebase_fs_hz(tier)` 取标轴用的 fs）。
    """
    if tier not in TIMEBASE_SAMPLE_RATES:
        raise ValueError(
            "tier 必须属于当前开放的档位 %s（T%d～T%d）；T3/T4 已于 2026-10-14 屏蔽"
            % (
                "/".join(str(k) for k in sorted(TIMEBASE_SAMPLE_RATES)),
                min(TIMEBASE_SAMPLE_RATES) + 1,
                max(TIMEBASE_SAMPLE_RATES) + 1,
            )
        )
    return build_command(0x8D, bytes([tier]))


def timebase_fs_hz(tier: int) -> float:
    """取某档位的等效采样率（Hz），用于给 0x8E 谱帧标频率轴。"""
    if tier not in TIMEBASE_SAMPLE_RATES:
        raise ValueError("tier 不属于当前开放的档位 %s" % sorted(TIMEBASE_SAMPLE_RATES))
    return float(TIMEBASE_SAMPLE_RATES[tier])


def command_ifft_filter(mask_lo: int, mask_hi: int) -> bytes:
    """
    生成 0x92 IFFT 频域滤波命令（协议 v1.22, 2026-10-16 新增）。

    在**最近一次正向 FFT 留下的频谱**上就地跑一遍反变换, 先把 [mask_lo, mask_hi]
    及其**镜像** bin 置零, 于是时域输出里这一段频率被滤掉。

    ⚠️ mask 要给**带宽**, 不要只给一根谱线: 加窗会把单音展宽成 ±1 bin,
       只掩中心那颗会漏掉两侧。实测: 只掩 bin100 时压制几乎为 0;
       掩 98..102 时压制达到 **34 dB**。

    ⚠️ 往返增益: 引擎每级 >>1, 往返必然衰减 1/N(1024)。输出约为输入的 1/1024,
       这是定点设计的固有限制, 不是 bug。
    """
    if not (0 <= mask_lo <= mask_hi <= 511):
        raise ValueError('要求 0 <= mask_lo <= mask_hi <= 511')
    return build_command(0x92, bytes([mask_lo & 0xFF, (mask_lo >> 8) & 0xFF,
                                      mask_hi & 0xFF, (mask_hi >> 8) & 0xFF]))


def command_set_overlap(on: bool) -> bytes:
    """
    生成 0x91 帧重叠开关命令（协议 v1.22, 2026-10-16 新增）。

    on=True  : 50% 帧重叠 —— 每帧只采 512 个新点, 前半复用上一帧的后半,
               帧间没有信号空白(抓瞬态), 且采集时间减半 -> 频谱刷新率约翻倍。
    on=False : 原来的整帧采集(默认, 保持既有已验证行为)。

    实现要点: 采集与 FFT 共用同一块 RAM(原地 FFT 会摧毁数据), 所以上一帧的后半
    先另存到 512x16 的独立小缓冲, 下一帧再预载回来。资源代价 = 几百 LUT, 不占 BRAM。
    仿真判据: 第2帧的前半逐点 == 第1帧的后半(0/512 不符)。
    """
    return build_command(0x91, bytes([1 if on else 0]))


def command_set_window(win: int) -> bytes:
    """
    生成 0x90 窗函数档位命令（协议 v1.22, 2026-10-16 新增）。

    win: 0=矩形(主瓣最窄, 频率精度最高, 副瓣 -13dB)
         1=Hann(默认, 副瓣 -31dB)
         2=Blackman(副瓣 -58dB, 泄漏最小, 主瓣最宽)

    物理依据: 泄漏只取决于谱线与 bin 的**距离**。落在整数 bin 时矩形窗最优;
    落在 bin 正中(半个 bin 偏移)时泄漏最严重, 此时用 Blackman 收益最大。
    仿真实测(bin 半偏移, 探针 bin100): 矩形 69 / Hann 32 / Blackman 24 (对数码)。
    """
    if win not in WINDOW_TIERS:
        raise ValueError("win 必须是 %s" % sorted(WINDOW_TIERS))
    return build_command(0x90, bytes([win]))


# [0x90] 窗函数档位 -> 名称 (单一事实源)
WINDOW_TIERS = {0: "矩形", 1: "Hann", 2: "Blackman"}


def command_request_spectrum() -> bytes:
    """
    生成 0x8E 幅度谱帧请求命令（空负载）。

    帧长 518B ≈ 11.2ms @460800，可 10~20 帧/s 连续请求；配合 0x8B 扫频即得瀑布图。
    解析用 `parse_spectrum_frame()`（非法帧会抛 ValueError）。
    """
    return build_command(0x8E, b"")


# ============================================================================
# [0x8F 预触发比例]（协议 v1.21 新增）
#   决定**触发点在 1024 点波形帧里的位置**：0%/25%/50%/75%
#   实现见 src/wave_frame.v v6.0（采样缓冲改为永不归零的环形，触发时锁存写指针）
# ============================================================================
PRETRIGGER_RATIO = {0: 0.0, 1: 0.25, 2: 0.5, 3: 0.75}
PRETRIGGER_LABEL = {0: "0%(默认)", 1: "25%", 2: "50%", 3: "75%"}


def command_set_pretrigger(level: int) -> bytes:
    """
    生成 0x8F 预触发比例命令（协议 v1.21）。

    level: 0=0%(默认) / 1=25% / 2=50% / 3=75%

      - 0%  : 帧首点 = 触发点（与 v1.20 及以前**逐位等价**）
      - 50% : 触发点位于帧**正中**（第 512 点）—— 图上能看到触发边沿**左侧**的半个波形

    ⚠️ 它是"档位"不是一次性开关：发出后持续有效，直到下次修改或复位（**复位回 0%**）。
    ⚠️ 静默命令（无 ACK）—— 只能靠波形图上**触发点的位置**判断是否生效。
    ⚠️ 与 0x89 配合：先发 `command_set_trigger()` 选触发模式 → 再发本命令选预触发档
       → 最后发 `command_request_waveform()` 请求波形。
    """
    if level not in PRETRIGGER_RATIO:
        raise ValueError("level 必须是 0/1/2/3（0%/25%/50%/75%）")
    return build_command(0x8F, bytes([level]))



def parse_ascii_line(line: bytes):
    """
    解析FPGA返回的ASCII行。

    同时兼容：
    F=0001000Hz V=1085\\r\\n     <- 测量行(v1.17: V 是 mV 的 4 位)
    F=0001000Hz V=1085\\r
    S=0001001\\r\\n
    A=0001099\\r\\n
    """
    line = line.rstrip(b"\r\n")

    match = MEASUREMENT_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "measurement",
            "frequency_hz": int(match.group(1)),
            "vpp_mv": int(match.group(2)),
        }

    match = PEAK_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "peak",
            "name": match.group(1).decode("ascii"),
            "frequency_hz": int(match.group(2)),
        }

    match = DUTY_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "duty",
            "duty_percent": float(match.group(1)),
            "pulse_width_us": int(match.group(2)),
        }

    match = WAVEFORM_TYPE_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "waveform_type",
            "waveform_type": int(match.group(1)),
        }

    match = SELF_FFT_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "self_fft_peak",
            "name": match.group(1).decode("ascii"),
            "frequency_hz": int(match.group(2)),
        }

    return None


def parse_waveform_frame(frame: bytes, sample_rate_hz: int = 50_000):
    """
    解析FPGA返回的波形帧。

    格式：
    5A A5 01 04 00 + 1024个样点 + SUM
    """
    if len(frame) < 6:
        raise ValueError("波形帧太短")

    if frame[:2] != FRAME_HEADER:
        raise ValueError("波形帧头错误")

    frame_type = frame[2]

    if frame_type != 0x01:
        raise ValueError(
            f"不是波形帧，TYPE=0x{frame_type:02X}"
        )

    payload_length = int.from_bytes(frame[3:5], "big")
    expected_length = 5 + payload_length + 1

    if len(frame) != expected_length:
        raise ValueError(
            f"帧长度错误：应为{expected_length}字节，"
            f"实际为{len(frame)}字节"
        )

    received_checksum = frame[-1]
    calculated_checksum = sum(frame[2:-1]) & 0xFF

    if received_checksum != calculated_checksum:
        raise ValueError(
            f"校验失败：收到0x{received_checksum:02X}，"
            f"计算得到0x{calculated_checksum:02X}"
        )

    samples = list(frame[5:-1])

    if len(samples) != 1024:
        raise ValueError(
            f"样点数量错误：应为1024，实际为{len(samples)}"
        )

    return {
        "type": "waveform",
        # 二进制波形帧本身不携带时基，调用方必须传入当前0x8D档位对应的fs。
        "sample_rate_hz": sample_rate_hz,
        "samples": samples,
    }


def parse_spectrum_frame(frame: bytes):
    """
    解析FPGA返回的512点幅度谱帧。

    格式：
    5A A5 02 02 00 + 512个8bit对数压缩幅度码 + SUM

    频率轴不在帧内，由当前0x8D时基决定：f[k] = k * fs / 1024。
    """
    if len(frame) < 6:
        raise ValueError("幅度谱帧太短")

    if frame[:2] != FRAME_HEADER:
        raise ValueError("幅度谱帧头错误")

    frame_type = frame[2]
    if frame_type != 0x02:
        raise ValueError(
            f"不是幅度谱帧，TYPE=0x{frame_type:02X}"
        )

    payload_length = int.from_bytes(frame[3:5], "big")
    if payload_length != 512:
        raise ValueError(
            f"幅度谱点数错误：应为512，实际为{payload_length}"
        )

    expected_length = 5 + payload_length + 1
    if len(frame) != expected_length:
        raise ValueError(
            f"帧长度错误：应为{expected_length}字节，"
            f"实际为{len(frame)}字节"
        )

    received_checksum = frame[-1]
    calculated_checksum = sum(frame[2:-1]) & 0xFF
    if received_checksum != calculated_checksum:
        raise ValueError(
            f"校验失败：收到0x{received_checksum:02X}，"
            f"计算得到0x{calculated_checksum:02X}"
        )

    return {
        "type": "spectrum",
        "magnitude_codes": list(frame[5:-1]),
    }

class StreamParser:
    """
    串口字节流解析器。

    可以从同一个串口流中分离：
    1. F/V/S/A文本行
    2. 0x5A 0xA5开头的二进制波形帧与幅度谱帧
    """

    MAX_PAYLOAD_LENGTH = 4096

    def __init__(self, sample_rate_hz: int = 50_000):
        self.buffer = bytearray()
        self.sample_rate_hz = sample_rate_hz

    def set_timebase(self, index: int):
        """更新后续波形事件使用的采样率；应与已发送的0x8D档位一致。"""
        try:
            self.sample_rate_hz = TIMEBASE_SAMPLE_RATES[index]
        except KeyError as error:
            raise ValueError(
                "时基档位必须属于当前开放的 %s（T3/T4 已于 2026-10-14 屏蔽）"
                % sorted(TIMEBASE_SAMPLE_RATES)
            ) from error

    def feed(self, data: bytes):
        """
        输入新收到的串口字节。

        返回已解析出的事件列表。
        """
        if data:
            self.buffer.extend(data)

        events = []

        while self.buffer:
            # 当前缓存以二进制帧头开始
            if self.buffer.startswith(FRAME_HEADER):
                if len(self.buffer) < 5:
                    break

                payload_length = int.from_bytes(
                    self.buffer[3:5],
                    "big",
                )

                if payload_length > self.MAX_PAYLOAD_LENGTH:
                    # 长度明显异常，丢掉一个字节后重新寻找帧头
                    del self.buffer[0]
                    events.append({
                        "type": "protocol_error",
                        "message": f"异常负载长度：{payload_length}",
                    })
                    continue

                total_length = 5 + payload_length + 1

                if len(self.buffer) < total_length:
                    # 数据还没收完整，等待下一次feed()
                    break

                frame = bytes(self.buffer[:total_length])
                del self.buffer[:total_length]

                try:
                    frame_type = frame[2]
                    if frame_type == 0x01:
                        event = parse_waveform_frame(
                            frame,
                            sample_rate_hz=self.sample_rate_hz,
                        )
                    elif frame_type == 0x02:
                        event = parse_spectrum_frame(frame)
                    else:
                        raise ValueError(
                            f"不支持的二进制帧类型：0x{frame_type:02X}"
                        )
                    events.append(event)
                except ValueError as error:
                    events.append({
                        "type": "protocol_error",
                        "message": str(error),
                    })

                continue

            # 搜索二进制帧头
            header_index = self.buffer.find(FRAME_HEADER)

            # 搜索ASCII行结束符，同时兼容\r和\n
            cr_index = self.buffer.find(b"\r")
            lf_index = self.buffer.find(b"\n")

            line_end_candidates = [
                index
                for index in (cr_index, lf_index)
                if index >= 0
            ]

            line_end = (
                min(line_end_candidates)
                if line_end_candidates
                else -1
            )

            # ASCII结束符出现在二进制帧头之前
            if line_end >= 0 and (
                header_index < 0 or line_end < header_index
            ):
                line = bytes(self.buffer[:line_end])
                delimiter = self.buffer[line_end]
                del self.buffer[:line_end + 1]

                # 已处理\r，如果后面紧接\n，也一起移除
                if (
                    delimiter == 0x0D
                    and self.buffer.startswith(b"\n")
                ):
                    del self.buffer[0]

                if not line:
                    continue

                event = parse_ascii_line(line)

                if event is not None:
                    events.append(event)

                continue

            # 前面有无效数据，后面已经出现二进制帧头
            if header_index > 0:
                garbage = bytes(self.buffer[:header_index])
                del self.buffer[:header_index]

                events.append({
                    "type": "protocol_error",
                    "message": (
                        "丢弃无法解析的数据："
                        + garbage[:20].hex(" ")
                    ),
                })
                continue

            # 尚未收到完整ASCII行或二进制帧
            break

        return events

def run_self_test():
    """不连接板卡，检查协议代码是否正确。"""

    command_1k = command_set_frequency(1000)
    expected_1k = bytes.fromhex(
        "5A A5 85 00 04 E8 03 00 00 74"
    )
    assert command_1k == expected_1k

    command_1100 = command_set_second_frequency(1100)
    expected_1100 = bytes.fromhex(
        "5A A5 87 00 04 4C 04 00 00 DB"
    )
    assert command_1100 == expected_1100

    waveform_command = command_request_waveform()
    expected_waveform_command = bytes.fromhex(
        "5A A5 83 00 01 00 84"
    )
    assert waveform_command == expected_waveform_command

    assert command_set_waveform(1) == bytes.fromhex(
        "5A A5 88 00 01 01 8A"
    )
    assert command_set_trigger(1) == bytes.fromhex(
        "5A A5 89 00 01 01 8B"
    )
    assert command_run_self_fft() == bytes.fromhex(
        "5A A5 8A 00 01 00 8B"
    )
    assert command_set_sweep(True) == bytes.fromhex(
        "5A A5 8B 00 01 01 8D"
    )
    assert command_set_sweep(False) == bytes.fromhex(
        "5A A5 8B 00 01 00 8C"
    )
    # 0x8C 电压标定(v1.17): KN=1024 -> 原始LSB模式; KN=37203 -> 默认 36.33mV/LSB
    assert command_set_vpp_cal(1024) == bytes.fromhex(
        "5A A5 8C 00 04 00 04 00 00 94"
    )
    assert command_set_vpp_cal(8000) == bytes.fromhex(
        "5A A5 8C 00 04 40 1F 00 00 EF"
    )
    assert command_set_vpp_cal() == command_set_vpp_cal(DEFAULT_VPP_KN)
    assert command_set_timebase(0) == bytes.fromhex(
        "5A A5 8D 00 01 00 8E"
    )
    assert command_set_timebase(1) == bytes.fromhex(
        "5A A5 8D 00 01 01 8F"
    )
    # [2026-10-14] T3/T4 已由上位机屏蔽 —— 现在**必须被拒绝**。
    #   判据理由：屏蔽档位若还能发出去，就是"发得出去但不生效"，
    #   比当场报错难排查得多（0x8D 是静默命令，没有 ACK）。
    for _blocked in (2, 3):
        try:
            command_set_timebase(_blocked)
        except ValueError:
            pass
        else:
            raise AssertionError("已屏蔽的 T%d 没有被拒绝" % (_blocked + 1))
    assert command_request_spectrum() == bytes.fromhex(
        "5A A5 8E 00 00 8E"
    )
    try:
        command_set_timebase(4)
    except ValueError:
        pass
    else:
        raise AssertionError("非法时基档位没有被拒绝")

    measurement = parse_ascii_line(
        b"F=0001000Hz V=1085\r\n"
    )
    assert measurement == {
        "type": "measurement",
        "frequency_hz": 1000,
        "vpp_mv": 1085,
    }

    old_measurement = parse_ascii_line(
        b"F=0037500Hz V=0134\r"
    )
    assert old_measurement["frequency_hz"] == 37500
    assert old_measurement["vpp_mv"] == 134

    # 3 位的旧格式必须**解析失败**, 否则会静默按错单位读数
    assert parse_ascii_line(b"F=0001000Hz V=133") is None

    main_peak = parse_ascii_line(
        b"S=0001001\r\n"
    )
    assert main_peak == {
        "type": "peak",
        "name": "S",
        "frequency_hz": 1001,
    }

    second_peak = parse_ascii_line(
        b"A=0001099\r\n"
    )
    assert second_peak == {
        "type": "peak",
        "name": "A",
        "frequency_hz": 1099,
    }

    assert parse_ascii_line(b"D=050.0% W=00500us\r\n") == {
        "type": "duty",
        "duty_percent": 50.0,
        "pulse_width_us": 500,
    }
    assert parse_ascii_line(b"TY=1\r\n") == {
        "type": "waveform_type",
        "waveform_type": 1,
    }
    assert parse_ascii_line(b"SF=0000976Hz\r\n") == {
        "type": "self_fft_peak",
        "name": "SF",
        "frequency_hz": 976,
    }

    spectrum_payload = bytes(index & 0xFF for index in range(512))
    spectrum_body = b"\x02\x02\x00" + spectrum_payload
    spectrum_frame = (
        FRAME_HEADER
        + spectrum_body
        + bytes([sum(spectrum_body) & 0xFF])
    )
    spectrum = parse_spectrum_frame(spectrum_frame)
    assert spectrum["type"] == "spectrum"
    assert spectrum["magnitude_codes"] == list(spectrum_payload)

    parser = StreamParser()
    assert parser.feed(spectrum_frame[:100]) == []
    assert parser.feed(spectrum_frame[100:]) == [spectrum]

    parser.set_timebase(1)
    assert parser.sample_rate_hz == 12_500

    waveform_payload = bytes(index & 0xFF for index in range(1024))
    waveform_body = b"\x01\x04\x00" + waveform_payload
    waveform_frame = (
        FRAME_HEADER
        + waveform_body
        + bytes([sum(waveform_body) & 0xFF])
    )
    waveform = parser.feed(waveform_frame)
    assert len(waveform) == 1
    assert waveform[0]["type"] == "waveform"
    assert waveform[0]["sample_rate_hz"] == 12_500
    assert waveform[0]["samples"] == list(waveform_payload)

    bad_spectrum_frame = bytearray(spectrum_frame)
    bad_spectrum_frame[-1] ^= 0x01
    try:
        parse_spectrum_frame(bytes(bad_spectrum_frame))
    except ValueError as error:
        assert "校验失败" in str(error)
    else:
        raise AssertionError("错误校验和的幅度谱帧没有被拒绝")
    # [v1.21 新增] 0x8F 预触发比例（我方新增功能，队友版无此项）
    assert command_set_pretrigger(0) == bytes.fromhex("5AA58F00010090")
    assert command_set_pretrigger(1) == bytes.fromhex("5AA58F00010191")
    assert command_set_pretrigger(2) == bytes.fromhex("5AA58F00010292")
    assert command_set_pretrigger(3) == bytes.fromhex("5AA58F00010393")
    assert PRETRIGGER_RATIO[2] == 0.5


    print("协议自检全部通过")
    print("设置1kHz：", command_1k.hex(" "))
    print("开启1.1kHz双音：", command_1100.hex(" "))
    print("请求波形：", waveform_command.hex(" "))
    print("测量解析：", measurement)
    print("主峰解析：", main_peak)
    print("第二峰解析：", second_peak)


if __name__ == "__main__":
    run_self_test()
