# -*- coding: utf-8 -*-
"""
WaveCore串口协议模块

负责：
1. 生成0x81、0x83、0x85、0x87命令
2. 解析F/V/S/A文本行
3. 解析1024点波形帧
"""

import re


FRAME_HEADER = b"\x5A\xA5"

MEASUREMENT_PATTERN = re.compile(
    rb"^F=(\d{7})Hz V=(\d{3})$"
)

PEAK_PATTERN = re.compile(
    rb"^([SA])=(\d{7})$"
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


def parse_ascii_line(line: bytes):
    """
    解析FPGA返回的ASCII行。

    同时兼容：
    F=0001000Hz V=133\\r\\n
    F=0001000Hz V=133\\r
    S=0001001\\r\\n
    A=0001099\\r\\n
    """
    line = line.rstrip(b"\r\n")

    match = MEASUREMENT_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "measurement",
            "frequency_hz": int(match.group(1)),
            "vpp_lsb": int(match.group(2)),
        }

    match = PEAK_PATTERN.fullmatch(line)
    if match:
        return {
            "type": "peak",
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

    measurement = parse_ascii_line(
        b"F=0001000Hz V=133\r\n"
    )
    assert measurement == {
        "type": "measurement",
        "frequency_hz": 1000,
        "vpp_lsb": 133,
    }

    old_measurement = parse_ascii_line(
        b"F=0037500Hz V=134\r"
    )
    assert old_measurement["frequency_hz"] == 37500
    assert old_measurement["vpp_lsb"] == 134

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

    print("协议自检全部通过")
    print("设置1kHz：", command_1k.hex(" "))
    print("开启1.1kHz双音：", command_1100.hex(" "))
    print("请求波形：", waveform_command.hex(" "))
    print("测量解析：", measurement)
    print("主峰解析：", main_peak)
    print("第二峰解析：", second_peak)


if __name__ == "__main__":
    run_self_test()