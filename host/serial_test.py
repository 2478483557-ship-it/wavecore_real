# -*- coding: utf-8 -*-

import sys
import time

import serial
from serial.tools import list_ports

from protocol import (
    StreamParser,
    command_request_waveform,
    command_set_frequency,
    command_set_second_frequency,
)


BAUD_RATE = 460800
DEFAULT_TEST_FREQUENCY_HZ = 37_500


def show_available_ports():
    ports = list(list_ports.comports())

    if not ports:
        print("没有发现串口")
        return []

    print("发现以下串口：")

    for port in ports:
        print(
            f"  {port.device}: "
            f"{port.description} "
            f"[{port.hwid}]"
        )

    return ports


def select_port():
    # 命令行指定，例如：
    # python serial_test.py COM5
    if len(sys.argv) >= 2:
        return sys.argv[1]

    ports = show_available_ports()

    if len(ports) == 1:
        print(f"自动选择：{ports[0].device}")
        return ports[0].device

    if len(ports) > 1:
        print()
        print("存在多个串口，请指定端口，例如：")
        print("python serial_test.py COM5")

    return None


def select_test_frequency():
    """从命令行读取测试频率。

    用法：python serial_test.py COM4 37500
    未指定时默认测试37.5kHz。
    """
    if len(sys.argv) >= 3:
        try:
            return int(sys.argv[2])
        except ValueError as error:
            raise ValueError("测试频率必须是整数Hz") from error

    return DEFAULT_TEST_FREQUENCY_HZ


def select_second_frequency():
    """读取可选的第二频率。

    用法：python serial_test.py COM4 1000 1100
    未提供第四个参数时保持单音。
    """
    if len(sys.argv) < 4 or sys.argv[3] == "--wave":
        return None

    try:
        return int(sys.argv[3])
    except ValueError as error:
        raise ValueError("第二频率必须是整数Hz") from error


def should_request_waveform():
    """命令行中包含--wave时请求一次波形。

    单音波形：python serial_test.py COM4 1000 --wave
    双音波形：python serial_test.py COM4 1000 1100 --wave
    """
    return "--wave" in sys.argv[3:]


def print_event(event):
    event_type = event["type"]

    if event_type == "measurement":
        print(
            "[测量] "
            f"F={event['frequency_hz']} Hz  "
            f"Vpp={event['vpp_mv']} mV"
        )

    elif event_type == "peak":
        name = event["name"]
        description = "主峰" if name == "S" else "第二峰"

        print(
            f"[频谱] {name} {description}="
            f"{event['frequency_hz']} Hz"
        )

    elif event_type == "duty":
        print(
            "[时域] "
            f"D={event['duty_percent']:.1f}%  "
            f"W={event['pulse_width_us']} us"
        )

    elif event_type == "waveform_type":
        names = {0: "方波", 1: "正弦", 2: "三角", 3: "其他"}
        value = event["waveform_type"]
        print(f"[识别] TY={value} {names.get(value, '未知')}")

    elif event_type == "self_fft_peak":
        print(
            f"[自研FFT] {event['name']}="
            f"{event['frequency_hz']} Hz"
        )

    elif event_type == "waveform":
        samples = event["samples"]

        print(
            "[波形] "
            f"收到{len(samples)}点，"
            f"采样率={event['sample_rate_hz']} Hz，"
            f"最小值={min(samples)}，"
            f"最大值={max(samples)}"
        )

    elif event_type == "protocol_error":
        print("[协议错误]", event["message"])


def main():
    port_name = select_port()

    if port_name is None:
        return

    try:
        test_frequency_hz = select_test_frequency()
        test_frame = command_set_frequency(test_frequency_hz)
        second_frequency_hz = select_second_frequency()
        second_frame = (
            command_set_second_frequency(second_frequency_hz)
            if second_frequency_hz is not None
            else None
        )
        request_waveform = should_request_waveform()
        waveform_frame = (
            command_request_waveform()
            if request_waveform
            else None
        )
    except ValueError as error:
        print("频率参数错误：", error)
        return

    parser = StreamParser()

    print(f"正在打开 {port_name}，波特率{BAUD_RATE}……")

    try:
        with serial.Serial(
            port=port_name,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        ) as port:
            print("串口已连接，按Ctrl+C停止")

            # 清除连接前遗留的不完整串口数据
            port.reset_input_buffer()

            # 通过0x85命令设置测试主频
            print(
                f"发送{test_frequency_hz}Hz命令：",
                test_frame.hex(" "),
            )
            port.write(test_frame)
            port.flush()

            if second_frame is not None:
                # 等待主频命令处理完成，再开启第二频率
                time.sleep(0.1)
                print(
                    f"发送第二频率{second_frequency_hz}Hz命令：",
                    second_frame.hex(" "),
                )
                port.write(second_frame)
                port.flush()

            if waveform_frame is not None:
                # 等待设频生效并积累一段新波形后再请求
                time.sleep(0.3)
                print("发送波形请求：", waveform_frame.hex(" "))
                port.write(waveform_frame)
                port.flush()

            print("命令已发送，等待FPGA测量结果")

            while True:
                read_size = max(port.in_waiting, 1)
                data = port.read(read_size)

                for event in parser.feed(data):
                    print_event(event)

                time.sleep(0.005)

    except serial.SerialException as error:
        print("串口错误：", error)

    except KeyboardInterrupt:
        print()
        print("程序已停止")


if __name__ == "__main__":
    main()
