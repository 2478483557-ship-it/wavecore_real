# -*- coding: utf-8 -*-
"""一次性诊断：官方 FFT 是否停更 / T4 下波形识别 / 神经网络法表现。

回答三个问题：
  1. IP FFT（4096 点，串口那条 S= 行）在 T1/T3/T4 下是否还在更新
  2. T4 + 100kHz 时 TY 为什么报"其他"（顺带看 0x9D 的内部量）
  3. 神经网络法（0x96=1）在同一批频点上的表现

用法（跑之前先把上位机 GUI 关掉，否则串口被占用）：
    python diag_fft_ty.py COM5
"""
import re
import sys
import time

import serial

BAUD = 460800


def fr(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


class B:
    def __init__(self, port):
        self.s = serial.Serial(port, BAUD, timeout=0)
        time.sleep(1.5)
        self.s.reset_input_buffer()

    def send(self, f, wait=0.25):
        self.s.write(f)
        self.s.flush()
        time.sleep(wait)

    def rd(self, sec):
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < sec:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
        return buf.decode("ascii", "ignore")

    def wd(self):
        """0x9D 回读：返回 (类型, span, hi_cnt)"""
        self.s.reset_input_buffer()
        self.send(fr(0x9D), 0.55)
        t = self.rd(0.35)
        sf = re.findall(r"SF=(\d+)", t)
        s2 = re.findall(r"S2=(\d+)", t)
        s3 = re.findall(r"S3=(\d+)", t)
        if not sf:
            return (None, None, None)
        return (int(sf[-1]) - 800000,
                int(s2[-1]) if s2 else None,
                int(s3[-1]) if s3 else None)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    b = B(port)

    print("=" * 74)
    print("诊断 1：IP FFT（S= 行）是否还在更新")
    print("=" * 74)
    print("  档位  频率      S=行数/3s   S值样本                    含义")
    for sel, name in ((0, "T1"), (2, "T3"), (3, "T4")):
        b.send(fr(0x8D, bytes([sel])), 0.4)
        b.send(fr(0x85, (100000).to_bytes(4, "little")), 0.8)
        t = b.rd(3.0)
        ss = re.findall(r"S=(\d+)", t)
        note = "正常更新" if len(ss) >= 3 else ("★ 停更" if ss else "★ 完全没有")
        print("  %-4s %-8d %-10d %-27s %s"
              % (name, 100000, len(ss), ",".join(ss[:3]) if ss else "无", note))

    print()
    print("=" * 74)
    print("诊断 2：T4 下 100kHz 的波形识别（规则法）")
    print("=" * 74)
    b.send(fr(0x8D, bytes([3])), 0.4)
    b.send(fr(0x96, b"\x00"), 0.3)          # 规则法
    b.send(fr(0x99, bytes([0, 0])), 0.3)
    print("  波形  频率      TY行   内部类型  span  hi_cnt   判据窗口")
    for w, wname, exp in ((0, "正弦", 1), (1, "方波", 0), (2, "三角", 2)):
        b.send(fr(0x88, bytes([w])), 0.2)
        for hz in (10000, 100000):
            b.send(fr(0x85, hz.to_bytes(4, "little")), 0.8)
            t = b.rd(0.8)
            ty = re.findall(r"TY=(\d)", t)
            typ, span, hi = b.wd()
            ok = "✓" if (ty and ty[-1] == str(exp)) else "✗"
            print("  %-4s %-8d %-6s %-8s %-5s %-8s %s"
                  % (wname, hz, ty[-1] if ty else "-", typ, span, hi, ok))

    print()
    print("=" * 74)
    print("诊断 3：神经网络法（0x96=1）同批频点")
    print("=" * 74)
    b.send(fr(0x96, b"\x01"), 0.4)          # 切到神经网络
    print("  波形  频率      TY行   期望")
    for w, wname, exp in ((0, "正弦", 1), (1, "方波", 0), (2, "三角", 2)):
        b.send(fr(0x88, bytes([w])), 0.2)
        for hz in (10000, 100000):
            b.send(fr(0x85, hz.to_bytes(4, "little")), 0.8)
            t = b.rd(0.8)
            ty = re.findall(r"TY=(\d)", t)
            v = ty[-1] if ty else "-"
            print("  %-4s %-8d %-6s %s" % (wname, hz, v, "✓" if v == str(exp) else "✗"))

    # 收尾
    b.send(fr(0x96, b"\x00"), 0.3)
    b.send(fr(0x8D, bytes([0])), 0.3)
    b.send(fr(0x85, (1000).to_bytes(4, "little")), 0.3)
    b.s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
