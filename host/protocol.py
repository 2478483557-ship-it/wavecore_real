# -*- coding: utf-8 -*-
"""
WaveCore串口协议模块

负责：
1. 生成协议命令帧（0x81、0x83、0x85、0x87～**0x8F**；**v1.17 起 `V=` 是 4 位 mV**；
   **v1.20 起含 0x8D 时基四档 / 0x8E 幅度谱帧；v1.21 起含 0x8F 预触发比例**）
2. 解析F/V、S/A、D/W、TY、SF/S2/S3文本行
3. 解析1024点波形帧

v1.17 变更(2026-09-30, **文本行有破坏性改动**):
  - `V=` 字段由 3 位 ADC 计数(LSB) 改成 **4 位毫伏(mV)**: `F=0001000Hz V=1085`
  - 配套新增 0x8C 电压标定命令
  - 解析结果里的键名 `vpp_lsb` -> `vpp_mv`(单位变了, 名字必须跟着变, 否则会静默算错)
"""

import re


FRAME_HEADER = b"\x5A\xA5"

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
#   档位 -> (名字, 抽取比 decim, 等效采样率 fs_hz)
#   切换会同时改变：波形帧窗长 / 自研 FFT 的 Δf / IP FFT 窗长 / 频谱覆盖
# ============================================================================
TIMEBASE_TIERS = {
    0: ("T1", 1000, 50000),      # 默认；频谱覆盖 0~25kHz，自研 Δf=48.8Hz
    1: ("T2", 4000, 12500),      # 细分辨；0~6.25kHz，Δf=12.2Hz
    2: ("T3", 500, 100000),      # 展宽；0~50kHz，Δf=97.7Hz
    3: ("T4", 250, 200000),      # 超宽；0~100kHz，Δf=195.3Hz（范围换分辨率）
}


def command_set_timebase(tier: int) -> bytes:
    """
    生成 0x8D 时基档位命令（协议 v1.20）。

    tier: 0=T1 50kHz(默认) / 1=T2 12.5kHz / 2=T3 100kHz / 3=T4 200kHz

    ⚠️ **0x8D 是静默命令（没有 ACK / 回执行）** —— "发过去没反应"是**正常**的。
       只能靠可观察量判断生效：同一个 1kHz 方波，自研谱峰 bin 号会变
       （T1 bin20 / T2 bin82 / T3 bin10 / T4 bin5），波形帧里的周期数也会变（20/82/10/5）。

    ⚠️ 上位机必须**自己记住当前档位**：0x8E 谱帧本身不带 fs，
       否则频率轴会标错（`timebase_fs_hz(tier)` 取标轴用的 fs）。
    """
    if tier not in TIMEBASE_TIERS:
        raise ValueError("tier 必须是 0/1/2/3（T1/T2/T3/T4）")
    return build_command(0x8D, bytes([tier]))


def timebase_fs_hz(tier: int) -> float:
    """取某档位的等效采样率（Hz），用于给 0x8E 谱帧标频率轴。"""
    if tier not in TIMEBASE_TIERS:
        raise ValueError("tier 必须是 0/1/2/3（T1/T2/T3/T4）")
    return float(TIMEBASE_TIERS[tier][2])


# ============================================================================
# [0x8E 幅度谱帧]（协议 v1.18 新增）
#   请求：空负载 0x8E -> FPGA 触发一次自研 FFT 并回 518 字节二进制谱帧
#   帧格式：5A A5 | 02 | 02 00 | 512B 幅度码 | SUM
# ============================================================================
SPECTRUM_FRAME_HEAD = bytes([0x5A, 0xA5, 0x02, 0x02, 0x00])
SPECTRUM_BINS = 512
SPECTRUM_FRAME_LEN = 2 + 1 + 2 + SPECTRUM_BINS + 1          # 518


def command_request_spectrum() -> bytes:
    """
    生成 0x8E 幅度谱帧请求命令（空负载）。

    帧长约 11.2ms@460800，可 10~20 帧/s 连续请求；配合 0x8B 扫频即得瀑布图。
    """
    return build_command(0x8E, b"")


def parse_spectrum_frame(frame: bytes):
    """
    解析 518 字节幅度谱帧 -> 512 个幅度码（bytes）；不合法返回 None。

    幅度码是**对数压缩**后的值：`y = (b << 4) | frac4`（b 为 17bit L1 模的前导位），
    步进约 0.38dB、动态范围约 96dB。**它是相对量，不是 mV** ——
    只有"哪几个 bin 明显高出底噪"才是有意义的判读。
    """
    if len(frame) != SPECTRUM_FRAME_LEN or frame[:5] != SPECTRUM_FRAME_HEAD:
        return None
    if (sum(frame[2:-1]) & 0xFF) != frame[-1]:
        return None
    return frame[5:-1]


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


def parse_waveform_frame(frame: bytes):
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
        "sample_rate_hz": 50_000,
        "samples": samples,
    }

class StreamParser:
    """
    串口字节流解析器。

    可以从同一个串口流中分离：
    1. F/V/S/A文本行
    2. 0x5A 0xA5开头的二进制波形帧
    """

    MAX_PAYLOAD_LENGTH = 4096

    def __init__(self):
        self.buffer = bytearray()

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
                    event = parse_waveform_frame(frame)
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

    # [v1.20 新增] 时基档位与幅度谱帧
    assert command_set_timebase(0) == bytes.fromhex("5AA58D0001008E")
    assert command_set_timebase(1) == bytes.fromhex("5AA58D0001018F")
    assert command_set_timebase(2) == bytes.fromhex("5AA58D00010290")
    assert command_set_timebase(3) == bytes.fromhex("5AA58D00010391")
    assert [timebase_fs_hz(i) for i in range(4)] == [50000.0, 12500.0, 100000.0, 200000.0]
    assert command_request_spectrum() == bytes.fromhex("5AA58E00008E")
    # [v1.21 新增] 预触发比例
    assert command_set_pretrigger(0) == bytes.fromhex("5AA58F00010090")
    assert command_set_pretrigger(1) == bytes.fromhex("5AA58F00010191")
    assert command_set_pretrigger(2) == bytes.fromhex("5AA58F00010292")
    assert command_set_pretrigger(3) == bytes.fromhex("5AA58F00010393")
    assert PRETRIGGER_RATIO[2] == 0.5
    _sf = b"\x5a\xa5\x02\x02\x00" + bytes(512) + bytes([0x04])
    assert parse_spectrum_frame(_sf) == bytes(512)
    assert parse_spectrum_frame(_sf[:-1]) is None        # 长度不对
    assert parse_spectrum_frame(_sf[:-1] + b"\x05") is None   # 校验和不对

    print("协议自检全部通过")
    print("设置1kHz：", command_1k.hex(" "))
    print("开启1.1kHz双音：", command_1100.hex(" "))
    print("请求波形：", waveform_command.hex(" "))
    print("测量解析：", measurement)
    print("主峰解析：", main_peak)
    print("第二峰解析：", second_peak)


if __name__ == "__main__":
    run_self_test()
