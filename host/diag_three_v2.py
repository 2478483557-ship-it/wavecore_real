# -*- coding: utf-8 -*-
"""三项功能的细化实测（第一版诊断的结论需要修正）。

① 自适应选窗：扫一批频率，同时看 SF 是否走插值（用来判断判决有没有机会更新）
   以及 WIN= 到底选了哪个窗。
② 谱平均：**不能只看中位数** —— 中位数本来就不该变。要测逐 bin 的帧间标准差。
③ 自研 FFT 三峰：细扫基频，看第三峰从哪个频率开始不可靠。
"""
import re
import statistics
import sys
import time

import serial
import protocol

BAUD = 460800
FS = 50000
DF = FS / 1024.0


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def drain(ser, sec=0.9):
    ser.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < sec:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
    return buf.decode("ascii", "ignore")


def set_freq(ser, hz, wave=0):
    ser.write(frame(0x88, bytes([wave]))); ser.flush(); time.sleep(0.12)
    ser.write(frame(0x85, hz.to_bytes(4, "little"))); ser.flush(); time.sleep(0.40)


def run_fft(ser):
    ser.reset_input_buffer()
    ser.write(frame(0x8A, b"\x00")); ser.flush()
    txt = drain(ser, 1.4)
    out = {}
    for k in ("SF", "S2", "S3"):
        m = re.search(r"%s=(\d+)" % k, txt)
        out[k] = int(m.group(1)) if m else None
    m = re.search(r"WIN=(RECT|HANN|BLK)", txt)
    out["WIN"] = m.group(1) if m else None
    return out


def one_spec(ser):
    ser.reset_input_buffer()
    ser.write(frame(0x8E, b"\x00")); ser.flush()
    buf = bytearray(); t0 = time.time()
    while time.time() - t0 < 1.6:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        h = buf.find(b"\x5a\xa5\x02")
        if h >= 0 and len(buf) >= h + 518:
            try:
                return protocol.parse_spectrum_frame(bytes(buf[h:h + 518]))["magnitude_codes"]
            except Exception:                       # noqa: BLE001
                buf = buf[h + 1:]
    return None


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    ser = serial.Serial(port, BAUD, timeout=0)
    time.sleep(1.0)
    if b"F=" not in drain(ser, 1.2).encode():
        print("板子无输出"); return 2

    # ============ ① 自适应选窗 ============
    print("=" * 74)
    print("① 自适应选窗：SF 是否等于「整数 bin」可以用来判断插值有没有跑")
    print("=" * 74)
    ser.write(frame(0x90, bytes([1]))); ser.flush(); time.sleep(0.25)   # 手动 Hann
    ser.write(frame(0x97, b"\x01")); ser.flush(); time.sleep(0.25)      # 开自适应

    print("  %-7s %-8s %-9s %-7s %-7s %s" % ("设定", "理论bin", "整数bin值", "SF", "插值?", "WIN"))
    print("  " + "-" * 66)
    for f in (488, 537, 586, 635, 684, 733, 781, 830, 879, 928, 977, 1025):
        binpos = f / DF
        intbin = int(binpos) * DF
        set_freq(ser, f, wave=0)
        r = run_fft(ser)
        inside = "是" if (r["SF"] is not None and abs(r["SF"] - intbin) > 1.0) else "否"
        print("  %-7d %-8.2f %-9.1f %-7s %-7s %s"
              % (f, binpos, intbin, r["SF"], inside, r["WIN"]))

    ser.write(frame(0x97, b"\x00")); ser.flush(); time.sleep(0.2)

    # ============ ② 谱平均：测帧间标准差 ============
    print()
    print("=" * 74)
    print("② 谱平均：测逐 bin 的帧间标准差（中位数本来就不该变）")
    print("=" * 74)
    set_freq(ser, 1000, wave=0)

    def collect(n):
        frames = []
        for _ in range(n):
            s = one_spec(ser)
            if s:
                frames.append(s)
        return frames

    def report(frames, label):
        if len(frames) < 3:
            print("   %s 取帧不足 (%d)" % (label, len(frames))); return None
        # 只看远离主峰的底噪区（bin 60~460），避开 1kHz 主峰(bin20)与谐波
        cols = list(zip(*[f[60:460] for f in frames]))
        stds = [statistics.pstdev(c) for c in cols]
        med = [statistics.median(f[60:460]) for f in frames]
        print("   %-10s 帧数%2d   底噪中位数 %s   帧间标准差均值 %.2f"
              % (label, len(frames),
                 "%.0f" % statistics.mean(med), statistics.mean(stds)))
        return statistics.mean(stds)

    ser.write(frame(0x98, b"\x00")); ser.flush(); time.sleep(0.3)
    f_off = collect(12)
    s_off = report(f_off, "平均关")

    ser.write(frame(0x98, b"\x01")); ser.flush(); time.sleep(0.3)
    collect(8)                                     # 让它收敛，不计入
    f_on = collect(12)
    s_on = report(f_on, "平均开")

    if s_off and s_on:
        print("   → 标准差之比 %.2f（理论 1/√8 ≈ 0.35，即降到约 1/3）"
              % (s_on / s_off))
    ser.write(frame(0x98, b"\x00")); ser.flush()

    # ============ ③ 自研 FFT 三峰 ============
    print()
    print("=" * 74)
    print("③ 自研 FFT 三峰细扫（方波）")
    print("=" * 74)
    print("  %-6s %-7s %-8s %-8s %-8s %-8s %s"
          % ("基频", "SF", "S2", "S2/3", "S3", "S3/5", "判定"))
    print("  " + "-" * 70)
    for f in (500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000):
        set_freq(ser, f, wave=1)
        r = run_fft(ser)
        s2, s3 = r["S2"] or 0, r["S3"] or 0
        h2 = s2 / 3.0 if s2 else 0
        h3 = s3 / 5.0 if s3 else 0

        if not s3:
            verdict = "第三峰为 0（5f=%.0f %s）" % (
                f * 5, "超界" if f * 5 > 24951 else "在界内")
        else:
            err = abs(h3 - f) / f * 100
            if err > 10:
                verdict = "★ 第三峰错：疑似 7 次谐波(%.0f)" % (s3 / 7.0)
            elif err > 2:
                verdict = "偏差 %.0f%%" % err
            else:
                verdict = "正确"
        print("  %-6d %-7s %-8s %-8.0f %-8s %-8.0f %s"
              % (f, r["SF"], s2, h2, s3, h3, verdict))

    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
