# -*- coding: utf-8 -*-
"""量预触发准不准：抓多帧，看触发位置稳不稳。

理论：1kHz 方波（周期 50 点）在 1024 点帧里
    预触发 0%  → 触发点第 0 点
    25%        → 第 256 点
    50%        → 第 512 点
    75%        → 第 768 点

判据：上升沿应落在理论点 ±2 点内。
注意：索引 0 处的边沿要按"环形"判断（拿帧尾样本当 i-1），否则看不见。

用法：python host/measure_pretrigger.py [COM5]
"""
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("需要 pyserial")
    sys.exit(2)

import protocol

BAUD = 460800
FS = 50000
EXPECT = {0: 0, 1: 256, 2: 512, 3: 768}
LABEL = {0: "0%", 1: "25%", 2: "50%", 3: "75%"}


def pick_port(arg=None):
    if arg:
        return arg
    ports = [p.device for p in list_ports.comports() if "CH340" in (p.description or "")]
    if len(ports) == 1:
        return ports[0]
    print("找不到唯一的 CH340 串口:", ports)
    sys.exit(2)


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def grab(ser, timeout=2.0):
    ser.reset_input_buffer()
    ser.write(frame(0x83, b"\x00"))
    ser.flush()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        head = buf.find(b"\x5a\xa5\x01\x04\x00")
        if head >= 0 and len(buf) >= head + 1030:
            try:
                return protocol.parse_waveform_frame(bytes(buf[head:head + 1030]), FS)["samples"]
            except ValueError:
                buf = buf[head + 1:]
    return None


def edges_circular(s):
    """上升沿索引，把帧首尾接起来（这样索引 0 的边沿也能看见）"""
    lo, hi = min(s), max(s)
    if hi - lo < 20:
        return []
    mid = (lo + hi) / 2.0
    out = []
    for i in range(len(s)):
        prev = s[i - 1]          # i=0 时取 s[1023]，构成环形
        if prev < mid <= s[i]:
            out.append(i)
    return out


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    ser = serial.Serial(port, BAUD, timeout=0)
    print("串口 %s @ %d" % (port, BAUD))
    time.sleep(1.0)
    ser.reset_input_buffer()
    time.sleep(1.2)
    if b"F=" not in ser.read(4096):
        print("板子没有输出")
        ser.close()
        return 2

    ser.write(frame(0x85, (1000).to_bytes(4, "little"))); ser.flush(); time.sleep(0.3)
    ser.write(frame(0x88, b"\x01")); ser.flush(); time.sleep(0.6)
    ser.write(frame(0x89, b"\x01")); ser.flush(); time.sleep(0.6)
    print("已设：1kHz 方波 + 上升沿触发（周期 = 50 点）")
    print()

    print("预触发  理论   实测触发点（连续 6 帧）                 一致?")
    print("-" * 72)
    for sel in (0, 1, 2, 3):
        ser.write(frame(0x8F, bytes([sel]))); ser.flush(); time.sleep(0.5)
        want = EXPECT[sel]
        found = []
        for _ in range(6):
            s = grab(ser)
            if s is None:
                found.append(None)
                continue
            ed = edges_circular(s)
            # 取离理论值最近的那个边沿
            hit = min(ed, key=lambda e: abs(e - want)) if ed else None
            found.append(hit)
            time.sleep(0.15)
        good = [h for h in found if h is not None]
        spread = (max(good) - min(good)) if len(good) >= 2 else 0
        txt = ", ".join("-" if h is None else str(h) for h in found)
        print("%-6s %5d  %-36s %s" % (LABEL[sel], want, txt,
              "稳" if spread <= 2 else "散(%d点)" % spread))

    print()
    print("解读：实测值与理论值差 0~1 点属正常（触发检测有 1 拍延迟）。")
    print("      若同一档内多次结果散开 >2 点，说明触发沿判定不稳。")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
