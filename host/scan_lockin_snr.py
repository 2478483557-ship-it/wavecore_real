# -*- coding: utf-8 -*-
"""锁相放大 SNR 扫描 —— 一条曲线，替掉单点结论。

为什么需要这个：
    之前只有一个工作点（-0.5dB 下误差 2%）。单点不能说明"能捞到多深"，
    评委问一句"再差一点还行吗"就答不上来。
    本脚本扫 att（信号衰减）x noise（噪声档位），给出 SNR 全程的表现。

判据怎么算的：
    sig_lsb  = 基准峰值码 / 2^att          （att 每加 1，信号减半）
    nz_rms   = (127 >> (8-level)) / 2 / sqrt(3)   （LFSR 高 8 位，近似均匀分布）
    SNR_dB   = 20*log10(sig_lsb / nz_rms)

用法：
    python scan_lockin_snr.py            # 默认 COM5
    python scan_lockin_snr.py COM3
"""
import math
import re
import statistics
import sys
import time

import serial

KN = 36.33          # 模块输入端 mV / LSB（0x8C 标定 KN=37203）
FULL_REF = 32767.0  # Q1.15 参考满量程
FREQ_HZ = 1000


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


class Rig:
    def __init__(self, port):
        self.s = serial.Serial(port, 460800, timeout=0)

    def send(self, data, wait=0.3):
        self.s.write(data)
        self.s.flush()
        time.sleep(wait)

    def _drain(self, sec):
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < sec:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
        return bytes(buf)

    def vpp_mv(self):
        self.s.reset_input_buffer()
        text = self._drain(1.0).decode("ascii", "ignore")
        hits = re.findall(r"V=(\d+)", text)
        return int(hits[-1]) if hits else None

    def lockin_mv(self):
        """请求一帧 I/Q，换算成峰峰值 mV。"""
        self.s.reset_input_buffer()
        self.send(frame(0x9B), 0.8)
        raw = self._drain(0.6)

        head = raw.find(b"\x5a\xa5\x03")
        if head < 0 or len(raw) < head + 22:
            return None
        body = raw[head:head + 22]

        i_val = int.from_bytes(body[5:11], "little", signed=True)
        q_val = int.from_bytes(body[11:17], "little", signed=True)
        count = int.from_bytes(body[17:21], "little")
        if not count:
            return None

        amp_lsb = 2.0 * math.hypot(i_val, q_val) / (FULL_REF * count)
        return amp_lsb * 2.0 * KN


def analyze(rig, att, level, base_vpp):
    """设置一个工作点，返回该点的测量结果。"""
    rig.send(frame(0x99, bytes([level & 0x0F, att & 0x07])), 0.5)

    true_vpp = base_vpp / (2 ** att)
    sig_lsb = (base_vpp / 2.0 / KN) / (2 ** att)

    noise_amp = 0 if level == 0 else (127 >> (8 - level))
    noise_rms = (noise_amp / 2.0 / math.sqrt(3)) if noise_amp else 1e-3
    snr_db = 20 * math.log10(sig_lsb / noise_rms) if sig_lsb > 0 else -99.0

    direct = [rig.vpp_mv() for _ in range(3)]
    direct = [v for v in direct if v]
    direct_v = statistics.median(direct) if direct else 0

    lockin = [rig.lockin_mv() for _ in range(3)]
    lockin = [v for v in lockin if v]
    lockin_v = statistics.median(lockin) if lockin else 0

    return {
        "att": att, "level": level, "snr_db": snr_db,
        "true_vpp": true_vpp, "direct_vpp": direct_v, "lockin_vpp": lockin_v,
        "direct_err": 100 * (direct_v - true_vpp) / true_vpp if true_vpp else 0,
        "lockin_err": 100 * (lockin_v - true_vpp) / true_vpp if true_vpp else 0,
    }


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    rig = Rig(port)
    time.sleep(1.5)
    rig.s.reset_input_buffer()

    for f in (frame(0x8B, b"\x00"), frame(0x88, b"\x00"),
              frame(0x8D, b"\x00"),
              frame(0x85, FREQ_HZ.to_bytes(4, "little"))):
        rig.send(f, 0.25)

    rig.send(frame(0x9A, b"\x01"), 0.3)      # 开锁相
    rig.send(frame(0x9C, bytes([32, 0])), 0.3)   # 32 周期
    rig.send(frame(0x99, bytes([0, 0])), 0.4)    # 先关噪

    samples = [rig.vpp_mv() for _ in range(5)]
    samples = [v for v in samples if v]
    base = statistics.median(samples)
    print("基准 Vpp = %.0f mV（1kHz 正弦，无噪无衰减）\n" % base)

    points = [(0, 0), (0, 6), (1, 6), (2, 6), (3, 6), (3, 8), (4, 8)]
    rows = [analyze(rig, att, lvl, base) for att, lvl in points]

    print("  SNR_dB   真值Vpp   直接测量   直接误差    锁相测量   锁相误差")
    print("  " + "-" * 64)
    for r in rows:
        print("  %-8.1f %-9.0f %-10.0f %+9.0f%%  %-10.0f %+8.1f%%"
              % (r["snr_db"], r["true_vpp"], r["direct_vpp"], r["direct_err"],
                 r["lockin_vpp"], r["lockin_err"]))

    worst = min(rows, key=lambda r: r["snr_db"])
    print("\n  最差点：SNR %.1f dB，直接测量偏 %+.0f%%，锁相误差 %+.1f%%"
          % (worst["snr_db"], worst["direct_err"], worst["lockin_err"]))

    rig.send(frame(0x99, bytes([0, 0])), 0.3)
    rig.send(frame(0x9A, b"\x00"), 0.3)
    rig.s.close()


if __name__ == "__main__":
    main()
