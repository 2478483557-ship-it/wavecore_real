# -*- coding: utf-8 -*-
"""
WaveCore 串口上位机 - 起步代码(给队友1)
功能: 连接板卡串口 -> 实时解析 F=/S=/A= 行 -> 终端打印(可再包成 UI)
依赖: pip install pyserial
用法: 改下面 COM3 为你板卡的端口号, 运行后板卡开机即有数据流
协议: 见 board/uart_protocol.md v1.2
"""
import serial
import re

# 解析规则(按协议固定宽度)
PAT_F = re.compile(rb"F=(\d{7})Hz V=(\d{3})\r\n")   # 测量行
PAT_P = re.compile(rb"([SA])=(\d{7})\r\n")           # 谱峰行(主峰/第二峰)


def send_freq(ser, hz, cmd=0x85):
    """向下发频率设置命令: 0x85=主频任意频率, 0x87=第二频率(双音)"""
    body = bytes([cmd, 0x00, 0x04]) + int(hz).to_bytes(4, "little")
    frame = bytes([0x5A, 0xA5]) + body + bytes([sum(body) & 0xFF])
    ser.write(frame)


def main(port: str = "COM3", baud: int = 460800):
    ser = serial.Serial(port, baud, timeout=1)
    print(f"已连接 {port} @{baud}")
    last_freq = None
    while True:
        line = ser.readline()
        if not line:
            continue
        m = PAT_F.match(line)
        if m:
            freq_hz, vpp = int(m.group(1)), int(m.group(2))
            last_freq = freq_hz
            print(f"[测量] 频率={freq_hz}Hz  Vpp={vpp}")
            continue
        m = PAT_P.match(line)
        if m:
            tag, hz = m.group(1).decode(), int(m.group(2))
            note = "主峰" if tag == "S" else "第二峰"
            print(f"[频谱] {tag} {note}={hz}Hz")


if __name__ == "__main__":
    import sys
    _p = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    _b = int(sys.argv[2]) if len(sys.argv) > 2 else 460800
    main(port=_p, baud=_b)   # 用法: python serial_monitor_starter.py COM5 [波特率]
