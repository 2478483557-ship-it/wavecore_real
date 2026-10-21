# -*- coding: utf-8 -*-
"""诊断三个问题：自适应选窗 / 谱平均 / 自研FFT 三峰范围。

用法：python host/diag_three.py [COM3]
"""
import re
import sys
import time

import serial
import protocol

BAUD = 460800
FS_T1 = 50000
DF = FS_T1 / 1024.0


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def drain(ser, sec=0.8):
    ser.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < sec:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
    return buf.decode("ascii", "ignore")


def do_fft(ser, wait=1.5):
    """跑一次自研 FFT（0x8A），返回原始文本"""
    ser.reset_input_buffer()
    ser.write(frame(0x8A, b"\x00"))
    ser.flush()
    return drain(ser, wait)


def parse_fft(text):
    """从 SF=/S2=/S3=/WIN= 行取值"""
    out = {}
    for key in ("SF", "S2", "S3"):
        m = re.search(r"%s=(\d+)" % key, text)
        out[key] = int(m.group(1)) if m else None
    m = re.search(r"WIN=(RECT|HANN|BLK)", text)
    out["WIN"] = m.group(1) if m else None
    return out


def set_freq(ser, hz, wave=0):
    ser.write(frame(0x88, bytes([wave])))
    ser.flush(); time.sleep(0.12)
    ser.write(frame(0x85, hz.to_bytes(4, "little")))
    ser.flush(); time.sleep(0.45)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    ser = serial.Serial(port, BAUD, timeout=0)
    time.sleep(1.0)
    print("串口 %s" % port)

    if b"F=" not in drain(ser, 1.2).encode():
        print("板子无输出")
        return 2

    # ================= ① 自适应选窗 =================
    print()
    print("=" * 62)
    print("① 自适应选窗（0x97）")
    print("=" * 62)
    set_freq(ser, 1000, wave=0)          # 1kHz 正弦
    ser.write(frame(0x90, bytes([1]))); ser.flush(); time.sleep(0.3)   # 先手动 Hann

    print("手动 Hann 时：")
    for _ in range(2):
        r = parse_fft(do_fft(ser))
        print("   SF=%-7s S2=%-7s S3=%-7s WIN=%s" % (r["SF"], r["S2"], r["S3"], r["WIN"]))

    ser.write(frame(0x97, b"\x01")); ser.flush(); time.sleep(0.3)      # 开自适应
    print("开自适应后（连续 6 次）：")
    wins = []
    for i in range(6):
        r = parse_fft(do_fft(ser))
        wins.append(r["WIN"])
        print("   %d  SF=%-7s S2=%-7s S3=%-7s WIN=%s" % (i + 1, r["SF"], r["S2"], r["S3"], r["WIN"]))
    print("   → WIN 序列: %s" % wins)

    # 换一个频偏更大的频率（频偏接近 0.5 bin）
    f_alias = int(round(20.5 * DF))       # 20.5 bin -> 频偏 0.5
    print("换到 %.0f Hz（频偏约 0.5 bin）：" % f_alias)
    set_freq(ser, f_alias, wave=0)
    for i in range(3):
        r = parse_fft(do_fft(ser))
        print("   %d  SF=%-7s WIN=%s" % (i + 1, r["SF"], r["WIN"]))

    # 换到整数 bin 附近（频偏接近 0）
    f_int = int(round(20.0 * DF))
    print("换到 %.0f Hz（频偏约 0，应该选矩形）：" % f_int)
    set_freq(ser, f_int, wave=0)
    for i in range(3):
        r = parse_fft(do_fft(ser))
        print("   %d  SF=%-7s WIN=%s" % (i + 1, r["SF"], r["WIN"]))

    ser.write(frame(0x97, b"\x00")); ser.flush(); time.sleep(0.2)

    # ================= ② 谱平均 =================
    print()
    print("=" * 62)
    print("② 谱平均（0x98）—— 连续 24 帧看底噪")
    print("=" * 62)
    set_freq(ser, 1000, wave=0)
    ser.write(frame(0x90, bytes([1]))); ser.flush(); time.sleep(0.2)

    def spec_floor(n=1):
        """抓 n 帧 512 点幅度谱，返回每帧的底噪中位数（code）"""
        vals = []
        for _ in range(n):
            ser.reset_input_buffer()
            ser.write(frame(0x8E, b"\x00")); ser.flush()
            buf = bytearray(); t0 = time.time()
            while time.time() - t0 < 1.5:
                k = ser.in_waiting
                if k:
                    buf += ser.read(k)
                h = buf.find(b"\x5a\xa5\x02")
                if h >= 0 and len(buf) >= h + 5 + 512 + 1:
                    try:
                        d = protocol.parse_spectrum_frame(bytes(buf[h:h + 518]))
                        vals.append(d["magnitude_codes"])
                    except Exception:
                        buf = buf[h + 1:]
        return vals

    print("平均关（0x98=0）：")
    ser.write(frame(0x98, b"\x00")); ser.flush(); time.sleep(0.3)
    for i in range(4):
        v = spec_floor(1)
        if v:
            import statistics
            med = statistics.median(v[0])
            print("   第%d帧 底噪中位数 %d" % (i + 1, med))

    print("平均开（0x98=1），前 12 帧看收敛：")
    ser.write(frame(0x98, b"\x01")); ser.flush(); time.sleep(0.3)
    import statistics
    for i in range(12):
        v = spec_floor(1)
        if v:
            print("   第%2d帧 底噪中位数 %d" % (i + 1, statistics.median(v[0])))
    ser.write(frame(0x98, b"\x00")); ser.flush()

    # ================= ③ 自研FFT 三峰范围 =================
    print()
    print("=" * 62)
    print("③ 自研 FFT 三峰：扫基频（方波，看三次/五次谐波）")
    print("=" * 62)
    print("  理论：bin N 对应 %.2f Hz；可用 bin 1~511 = 48.8~24951 Hz" % DF)
    print("  方波三次谐波 = 3f，五次 = 5f")
    print()
    print("  %-8s %-9s %-9s %-9s %-9s %s" % ("基频", "SF", "S2(=3f)", "S3(=5f)", "5f理论", "判定"))
    print("  " + "-" * 66)

    for f in (500, 1000, 2000, 3000, 4000, 5000, 6000, 8000):
        if f * 5 > FS_T1 / 2:
            note = "5f=%.0fHz 超奈奎斯特(25000)" % (f * 5)
        else:
            note = ""
        set_freq(ser, f, wave=1)          # 方波
        r = parse_fft(do_fft(ser))
        s2 = r["S2"]; s3 = r["S3"]
        theo3 = f * 3
        ok3 = "—"
        if s3 is not None and s3 > 0:
            err = abs(s3 - f * 5) / max(f * 5, 1) * 100
            ok3 = "%.1f%%" % err
        print("  %-8d %-9s %-9s %-9s %-9d %s" % (f, r["SF"], s2, s3, f * 5, note or ("S3误差 " + ok3)))

    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
