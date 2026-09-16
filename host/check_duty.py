# -*- coding: utf-8 -*-
"""
check_duty.py —— 对 0x83 波形帧做"独立审计": 电脑自己算占空比/最长高电平
用法: python check_duty.py COM5
会打印: 点数 / 中线 / duty% / 最长高电平时长(us) / 最长低电平时长
"""
import sys, time
import serial

COM = sys.argv[1] if len(sys.argv) > 1 else "COM3"
CMD = bytes([0x5A, 0xA5, 0x83, 0x00, 0x01, 0x00, 0x84])
HEAD = bytes([0x5A, 0xA5, 0x01])
FS = 50_000  # 50kHz


def main():
    ser = serial.Serial(COM, 115200, timeout=1)
    ser.reset_input_buffer()
    ser.write(CMD)
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 4:
        data = ser.read(ser.in_waiting or 1)
        if data:
            buf += data
        i = buf.find(HEAD)
        if i >= 0 and len(buf) >= i + 5:
            n = buf[i+3]*256 + buf[i+4]
            if len(buf) >= i + 5 + n + 1:
                s = list(buf[i+5:i+5+n])
                break
    else:
        print("没收到波形帧")
        return

    lo, hi = min(s), max(s)
    mid = (lo + hi) // 2
    high = [1 if x > mid else 0 for x in s]
    duty = sum(high) / len(high) * 100
    # 最长连续高/低
    def longest(seq, val):
        best = cur = 0
        for x in seq:
            cur = cur + 1 if x == val else 0
            best = max(best, cur)
        return best
    rh = longest(high, 1)
    rl = longest(high, 0)
    print(f"点数={len(s)} min={lo} max={hi} 中线={mid}")
    print(f"duty = {duty:.1f} %")
    print(f"最长高电平 = {rh} 点 = {rh/FS*1e6:.0f} us")
    print(f"最长低电平 = {rl} 点 = {rl/FS*1e6:.0f} us")
    print(f"（板子报的对比看 D= / W= 两行）")


if __name__ == "__main__":
    main()
