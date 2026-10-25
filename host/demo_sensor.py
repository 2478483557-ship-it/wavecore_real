# -*- coding: utf-8 -*-
"""外部传感器演示 —— 用真实信号走一遍。

和 demo_weak_signal.py 的区别：
    那个用内部回环，真值已知，能算出误差百分比；
    这个接真传感器，**没有真值**，只能看"能不能稳定读出来"。

为什么还要做这个：
    内部回环证明的是算法，外部传感器证明的是**接口和前端真的能用**。
    评委看到麦克风/压电片接到板子上还能出数，和看到板子自己回环，感受不一样。

激励怎么来：
    锁相必须有**同频参考**，没有参考就锁不住。
    所以用板子的 DA 输出 → 小喇叭/压电片发声 → 传感器接收 → AD 输入端。
    这样激励和参考同源，锁相才能工作。

用法：
    python demo_sensor.py            # 默认 COM5
    python demo_sensor.py COM3
"""
import math
import re
import statistics
import sys
import time

import serial

from port_pick import pick_port

KN = 36.33
FULL_REF = 32767.0
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

    def measure(self, sec=1.2):
        """读一帧测量结果：频率、峰峰值、占空比。"""
        self.s.reset_input_buffer()
        text = self._drain(sec).decode("ascii", "ignore")
        freq = re.findall(r"F=(\d+)", text)
        vpp = re.findall(r"V=(\d+)", text)
        return (
            int(freq[-1]) if freq else None,
            int(vpp[-1]) if vpp else None,
        )

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

    def fft_peaks(self):
        """跑一次自研 FFT，返回 (SF, S2, S3)。"""
        self.send(frame(0x8A), 1.5)
        text = self._drain(0.5).decode("ascii", "ignore")
        out = []
        for name in ("SF", "S2", "S3"):
            m = re.findall(name + r"=(\d+)", text)
            out.append(int(m[-1]) if m else None)
        return tuple(out)


def banner(text):
    print()
    print("=" * 66)
    print(" " + text)
    print("=" * 66)


def sample(rig, n=5):
    """采 n 次，返回 (频率中位, Vpp中位, 锁相中位)。"""
    rows = []
    for _ in range(n):
        f, v = rig.measure(0.9)
        lk = rig.lockin_mv()
        if f is not None:
            rows.append((f, v, lk))
        time.sleep(0.1)
    if not rows:
        return None, None, None
    freqs = [r[0] for r in rows]
    vpps = [r[1] for r in rows if r[1] is not None]
    lks = [r[2] for r in rows if r[2] is not None]
    return (
        statistics.median(freqs),
        statistics.median(vpps) if vpps else None,
        statistics.median(lks) if lks else None,
    )


def fmt(value, unit=""):
    return "--" if value is None else "%.0f%s" % (value, unit)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    port = pick_port(arg)
    if port is None:
        return 1
    rig = Rig(port)
    time.sleep(1.5)
    rig.s.reset_input_buffer()

    banner("WaveCore 外部传感器演示")

    print("  接线检查（按顺序做）：")
    print("    1. 板子 DA 输出 ──> 小喇叭 / 压电片（作为声源）")
    print("    2. 麦克风/压电片 ──> 放大电路 ──> AD 模块输入端")
    print("    3. AD 模块 GND ── 放大电路 GND（必须共地）")
    print("    4. **拔掉原来的 DA→AD 回环飞线**")
    print()
    input("  接好了按回车继续……")

    # 初始化：1kHz 正弦，关噪声，开锁相
    for f in (frame(0x8B, b"\x00"), frame(0x88, b"\x00"),
              frame(0x8D, b"\x00"),
              frame(0x85, FREQ_HZ.to_bytes(4, "little"))):
        rig.send(f, 0.25)
    rig.send(frame(0x99, bytes([0, 0])), 0.4)
    rig.send(frame(0x9A, b"\x01"), 0.3)
    rig.send(frame(0x9C, bytes([32, 0])), 0.3)
    time.sleep(0.8)

    banner("第 1 步：确认收到信号")

    f0, v0, lk0 = sample(rig, 5)
    print("  声源 1kHz，传感器贴近：")
    print("    频率测量   %s Hz" % fmt(f0))
    print("    峰峰值     %s mV" % fmt(v0))
    print("    锁相幅度   %s mV" % fmt(lk0))

    if not v0 or v0 < 20:
        print()
        print("  [问题] 峰峰值太小（< 20mV），可能原因：")
        print("    · 声源没响 —— 确认喇叭接在 DA 输出上、音量够")
        print("    · AD 没收到 —— 回环飞线还没拔？或者传感器线接反")
        print("    · 增益不够 —— 需要运放放大")
        print()
        print("  先把第 1 步跑通，再往下走。")
        rig.s.close()
        return 1

    if f0 and abs(f0 - FREQ_HZ) < 100:
        print()
        print("  ✓ 频率对上了 —— 声源和接收都正常。")
    else:
        print()
        print("  ⚠ 频率读数是 %s，与设定的 %d Hz 差得远。" % (fmt(f0), FREQ_HZ))
        print("    环境噪声可能盖过了信号。先贴近声源再试。")

    sf, s2, s3 = rig.fft_peaks()
    print()
    print("  自研 FFT 三峰：%s / %s / %s Hz" % (fmt(sf), fmt(s2), fmt(s3)))
    if sf and abs(sf - FREQ_HZ) < 100:
        print("  ✓ 频谱峰值也对上了。")

    input("\n  按回车进入下一步……")

    banner("第 2 步：拉远，看信号衰减")
    print("  把传感器**慢慢往远处移**，每移一次按一次回车。")
    print("  要观察的：直接测量什么时候开始乱跳，锁相什么时候才掉。")
    print()

    results = []
    for step in range(4):
        input("  移到第 %d 个距离点，按回车采样……" % (step + 1))
        f, v, lk = sample(rig, 5)
        vpp_std = None
        results.append((step + 1, f, v, lk))
        print("    位置%d   F=%-7s Vpp=%-7s 锁相=%-7s"
              % (step + 1, fmt(f), fmt(v), fmt(lk)))

    banner("汇总")

    print("  位置   F(Hz)    Vpp(mV)   锁相(mV)   说明")
    print("  " + "-" * 58)
    for idx, f, v, lk in results:
        note = ""
        if v is not None and v < 30:
            note = "信号已很弱"
        if f is not None and abs(f - FREQ_HZ) > 100:
            note = "频率已读错"
        print("  %-5d  %-8s %-10s %-10s %s"
              % (idx, fmt(f), fmt(v), fmt(lk), note))

    print()
    print("  看点：随着距离增加，Vpp 一路下降（这是物理规律），")
    print("        但锁相读数应该比 F 和 Vpp 更稳 —— 因为它按频率挑，")
    print("        不按峰值判。")

    rig.send(frame(0x9A, b"\x00"), 0.3)
    rig.s.close()
    print()
    print("  已恢复：锁相关。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
