# -*- coding: utf-8 -*-
"""锁相放大上板验证脚本。

做三件事：
  1. 回归——确认原有功能没被新模块影响（0x8A 自研 FFT、0x83 波形帧）
  2. 对比——同一信号下，"直接测量"和"锁相放大"两组读数放在一起
  3. 量化——扫噪声档位，出一张「误差 vs SNR」表

用法：
    python test_lockin.py COM5
    python test_lockin.py COM5 --freq 2000 --periods 32
"""
import math
import re
import statistics
import sys
import time

import serial

BAUD = 460800
KN = 37203.0 / 1024.0          # 每 LSB 对应多少 mV（模块输入端）
FULL_REF = 32767.0             # 参考幅度满量程（Q1.15）
FS = 25_000_000.0              # ADC 实际样点率


# ---------------------------------------------------------------- 组帧
def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def cmd_noise(level, att=0):
    """0x99：噪声档位 0..8，信号衰减 0..4"""
    return frame(0x99, bytes([level & 0x0F, att & 0x07]))


def cmd_lockin_on(on):
    return frame(0x9A, bytes([1 if on else 0]))


def cmd_lockin_req():
    return frame(0x9B, b"")


def cmd_lockin_periods(n):
    return frame(0x9C, bytes([n & 0xFF, (n >> 8) & 0xFF]))


def cmd_freq(hz):
    return frame(0x85, hz.to_bytes(4, "little"))


def cmd_wave(w):
    return frame(0x88, bytes([w]))


def cmd_self_fft():
    return frame(0x8A, b"\x00")


# ---------------------------------------------------------------- 收发
class Link:
    def __init__(self, port):
        self.s = serial.Serial(port, BAUD, timeout=0)
        time.sleep(1.5)
        self.s.reset_input_buffer()

    def drain(self, sec=0.6):
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < sec:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
        return bytes(buf)

    def send(self, f, wait=0.25):
        self.s.reset_input_buffer()
        self.s.write(f)
        self.s.flush()
        return self.drain(wait)

    def read_measure(self, sec=0.8):
        """读一条测量行，返回 (F, V, D, W, TY)。"""
        txt = self.drain(sec).decode("ascii", "ignore")
        out = {}
        for k in ("F", "V", "D", "W", "TY"):
            m = re.search(r"%s=(\d+)" % k, txt)
            out[k] = int(m.group(1)) if m else None
        return out

    def read_lockin(self, timeout=1.2):
        """请求并解析一帧 5A A5 03。"""
        self.s.reset_input_buffer()
        self.s.write(cmd_lockin_req())
        self.s.flush()
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < timeout:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
            h = buf.find(b"\x5a\xa5\x03")
            if h >= 0 and len(buf) >= h + 22:
                f = bytes(buf[h:h + 22])
                if sum(f[:21]) & 0xFF == f[21]:
                    i = int.from_bytes(f[5:11], "little", signed=True)
                    q = int.from_bytes(f[11:17], "little", signed=True)
                    n = int.from_bytes(f[17:21], "little")
                    return i, q, n
                buf = buf[h + 1:]
        return None

    def close(self):
        self.s.close()


# ---------------------------------------------------------------- 计算
def lockin_amp_lsb(i, q, n):
    """累加值 -> 输入正弦峰值（ADC 码）。"""
    if not n:
        return 0.0
    return 2.0 * math.hypot(i, q) / (FULL_REF * n)


def lockin_phase_deg(i, q):
    return math.degrees(math.atan2(q, i))


def amp_to_vpp_mv(amp_lsb):
    """峰值码 -> 模块输入端峰峰值 mV。"""
    return amp_lsb * 2 * KN


# ---------------------------------------------------------------- 主流程
def main():
    port = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "COM5"
    freq = 1000
    periods = 32
    for i, a in enumerate(sys.argv):
        if a == "--freq" and i + 1 < len(sys.argv):
            freq = int(sys.argv[i + 1])
        if a == "--periods" and i + 1 < len(sys.argv):
            periods = int(sys.argv[i + 1])

    lk = Link(port)
    # 先把上一轮可能残留的注噪/锁相清掉，否则回归那一段会被污染
    lk.send(cmd_noise(0, 0), 0.3)
    lk.send(cmd_lockin_on(False), 0.25)
    lk.send(cmd_freq(freq), 0.4)
    lk.send(cmd_wave(0), 0.3)
    lk.send(cmd_lockin_periods(periods), 0.3)

    print("=" * 72)
    print("锁相放大上板验证   %d Hz, 积分 %d 个周期" % (freq, periods))
    print("=" * 72)

    # ---- 1. 回归：原有功能是否仍正常 ----
    print("\n[1] 回归检查")
    r = lk.send(cmd_self_fft(), 1.4).decode("ascii", "ignore")
    sf = re.search(r"SF=(\d+)", r)
    print("    自研 FFT   SF = %s   %s" % (sf.group(1) if sf else "--",
                                       "OK" if sf else "★ 失效"))
    m = lk.read_measure()
    print("    测量行     F=%s V=%s D=%s W=%s TY=%s   %s"
          % (m["F"], m["V"], m["D"], m["W"], m["TY"],
             "OK" if m["F"] else "★ 失效"))

    # ---- 2. 无噪声基准 ----
    print("\n[2] 无噪声基准")
    lk.send(cmd_noise(0, 0), 0.4)
    lk.send(cmd_lockin_on(True), 0.4)
    base = []
    for _ in range(6):
        v = lk.read_lockin()
        if v:
            base.append(lockin_amp_lsb(*v))
        time.sleep(0.05)
    if not base:
        print("    ★ 收不到 I/Q 帧，检查 0x9A/0x9B 是否生效")
        lk.close()
        return 1
    b = statistics.mean(base)
    print("    锁相幅度 = %.2f LSB  ->  %.0f mV(峰峰)   波动 %.2f%%"
          % (b, amp_to_vpp_mv(b), statistics.pstdev(base) / b * 100 if b else 0))

    # ---- 3. 衰减 + 加噪：把信号埋进噪声，两组读数并排 ----
    #   注意：误差的参照是"同衰减、无噪声"时的锁相值，不是满幅基准。
    #   否则衰减本身就会被算成误差，看起来像锁相坏了。
    print("\n[3] 埋进噪声之后（真值 = 同衰减、无噪声时的锁相值）")
    print("    衰减 噪声  真值mV   直接V    直接误差   锁相mV   锁相误差")
    print("    " + "-" * 62)
    for att in (2, 3):
        lk.send(cmd_noise(0, att), 0.5)
        time.sleep(0.2)
        base_amp = []
        for _ in range(7):
            v = lk.read_lockin()
            if v:
                base_amp.append(lockin_amp_lsb(*v))
        if not base_amp:
            continue
        true_mv = amp_to_vpp_mv(statistics.median(base_amp))

        for lvl in (0, 4, 6, 7, 8):
            lk.send(cmd_noise(lvl, att), 0.45)
            time.sleep(0.15)
            vs, amps = [], []
            for _ in range(5):
                mm = lk.read_measure(0.45)
                if mm["V"] is not None:
                    vs.append(mm["V"])
                v = lk.read_lockin()
                if v:
                    amps.append(lockin_amp_lsb(*v))
            if not vs or not amps:
                continue
            vmed = statistics.median(vs)
            amed = statistics.median(amps)
            de = (vmed - true_mv) / true_mv * 100 if true_mv else 0
            le = (amp_to_vpp_mv(amed) - true_mv) / true_mv * 100 if true_mv else 0
            print("    %-4d %-4d %-8.0f %-8.0f %-10.0f%% %-8.0f %-7.1f%%"
                  % (att, lvl, true_mv, vmed, de, amp_to_vpp_mv(amed), le))
        print()

    # ---- 4. 关闭，恢复现场 ----
    lk.send(cmd_noise(0, 0), 0.3)
    lk.send(cmd_lockin_on(False), 0.3)
    print("\n[4] 已关闭注噪与锁相，DDS 恢复原状")
    lk.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
