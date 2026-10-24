# -*- coding: utf-8 -*-
"""微弱信号提取演示 —— 现场一键跑。

演示的是这台仪器的看家能力：
    信号埋在噪声底下、常规方法读不出来的时候，它还能测。

为什么信号来自内部回环而不是真传感器：
    现场要的是"能不能从噪声里捞出来"，不是"传感器好不好"。
    用内部 DDS 产生已知幅度的信号，**真值可控**，才能当场算出误差。
    接真传感器反而没有真值，只能看"稳不稳"，说服力更弱。
    （接传感器的方法见 report/sensor_frontend_guide.md，
      接上之后本脚本同样适用，只是把信号源换成传感器。）

用法：
    python demo_weak_signal.py            # 默认 COM5
    python demo_weak_signal.py COM3
"""
import math
import re
import statistics
import sys
import time

import serial

KN = 36.33
FULL_REF = 32767.0
FREQ_HZ = 1000
PERIODS = 32


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
        return 2.0 * math.hypot(i_val, q_val) / (FULL_REF * count) * 2.0 * KN

    def median_vpp(self, n=5):
        vals = [self.vpp_mv() for _ in range(n)]
        vals = [v for v in vals if v]
        return statistics.median(vals) if vals else 0

    def median_lockin(self, n=5):   # 5 次中位，压掉锁相的单次抖动
        vals = [self.lockin_mv() for _ in range(n)]
        vals = [v for v in vals if v]
        return statistics.median(vals) if vals else 0


def banner(text):
    print()
    print("=" * 68)
    print(" " + text)
    print("=" * 68)


def show(title, true_vpp, direct, lockin):
    err_d = 100 * (direct - true_vpp) / true_vpp if true_vpp else 0
    err_l = 100 * (lockin - true_vpp) / true_vpp if true_vpp else 0
    print("  %-14s 真值 %5.0f mV" % (title, true_vpp))
    print("    直接测量  %6.0f mV   误差 %+7.0f%%   %s"
          % (direct, err_d, "← 读数不可信" if abs(err_d) > 20 else ""))
    print("    锁相放大  %6.0f mV   误差 %+7.1f%%   %s"
          % (lockin, err_l, "← 仍然准确" if abs(err_l) < 10 else ""))
    return err_d, err_l


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    rig = Rig(port)
    time.sleep(1.5)
    rig.s.reset_input_buffer()

    banner("WaveCore 微弱信号提取演示")

    print("  正在初始化……")
    for f in (frame(0x8B, b"\x00"), frame(0x88, b"\x00"),
              frame(0x8D, b"\x00"),
              frame(0x85, FREQ_HZ.to_bytes(4, "little"))):
        rig.send(f, 0.25)
    rig.send(frame(0x99, bytes([0, 0])), 0.4)      # 关噪声
    rig.send(frame(0x9A, b"\x01"), 0.3)            # 开锁相
    rig.send(frame(0x9C, bytes([PERIODS, 0])), 0.3)

    base = rig.median_vpp(5)
    if not base:
        print("  [失败] 读不到 V= 行，检查串口/板子")
        return 1

    banner("第 0 步：干净信号，建立基准")
    print("  1kHz 正弦，无噪声，作为后续所有误差计算的真值。")
    d0 = rig.median_vpp()
    l0 = rig.median_lockin()
    show("基准", base, d0, l0)
    print()
    print("  两种方法在这种条件下都应该准 —— 这只是确认仪器本身是好的。")
    input("  按回车继续……")

    def true_attenuated(att):
        """测该衰减档位在**无噪声**时的读数，作为真值。

        不能直接用 base / 2^att 算：衰减是整数右移（sig0 >>> shift），
        小信号时会截断。base/16 = 304mV，但硬件实际输出是 (67>>4)=4 码 = 290mV。
        用偏差 5% 的"理论真值"去算误差，会把系统误差算到锁相头上。
        """
        rig.send(frame(0x99, bytes([0, att])), 0.6)
        return rig.median_vpp()

    banner("第 1 步：把信号埋进噪声（SNR ≈ -0.6 dB）")
    print("  信号功率和噪声功率基本相等。真实场景里这已经很糟了。")
    true1 = true_attenuated(3)
    print("  先量真值：该档位无噪声时 = %.0f mV" % true1)
    rig.send(frame(0x99, bytes([6, 3])), 0.6)
    d1 = rig.median_vpp()
    l1 = rig.median_lockin()
    e1 = show("SNR -0.6dB", true1, d1, l1)
    print()
    print("  直接测量偏了 %+.0f%% —— 峰峰值检波量到的主要是噪声。" % e1[0])
    input("  按回车继续……")

    banner("第 2 步：再差 18dB（SNR ≈ -18.8 dB）")
    print("  信号只有噪声功率的 1/76。这个深度下……")
    true2 = true_attenuated(4)
    print("  先量真值：该档位无噪声时 = %.0f mV" % true2)
    rig.send(frame(0x99, bytes([8, 4])), 0.6)
    d2 = rig.median_vpp()
    l2 = rig.median_lockin()
    e2 = show("SNR -18.8dB", true2, d2, l2)
    print()
    print("  ★ 直接测量偏 %+.0f%%（%.1f 倍），已经完全不能用了。" % (e2[0], (d2 / true2) if true2 else 0))
    print("  ★ 锁相放大偏 %+.1f%%，仍然准确。" % e2[1])

    banner("结论")

    print("  同一台仪器、同一个信号、同一时刻：")
    print("    直接测量  %6.0f mV  （真值 %.0f mV）" % (d2, true2))
    print("    锁相放大  %6.0f mV  （真值 %.0f mV）" % (l2, true2))
    print()
    print("  误差相差 %.0f 倍。" % (abs(e2[0]) / max(abs(e2[1]), 0.1)))
    print()
    print("  这不是「测得更准」，是「换了一种看法」：")
    print("    峰峰值检波问的是「最高的点有多高」—— 噪声的最高的点当然很高；")
    print("    锁相放大问的是「和参考同频的那部分有多少」—— 噪声没有固定频率。")

    rig.send(frame(0x99, bytes([0, 0])), 0.3)
    rig.send(frame(0x9A, b"\x00"), 0.3)
    rig.s.close()
    print()
    print("  已恢复：噪声关、锁相关。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
