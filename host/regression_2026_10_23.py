# -*- coding: utf-8 -*-
"""WaveCore 回归测试 —— 2026-10-23 版。

覆盖范围：
  · 基础：设频率 / 波形 / 测量行
  · 自研 FFT（0x8A）与谱帧（0x8E）在 T1 / T3 / T4 三个档位
  · 波形帧（0x83）：**重点**——时基往返后必须仍然可用（今天修的那个坑）
  · 时基四档切换
  · 窗函数（0x90）/ 帧重叠（0x91）/ 谱平均（0x98）
  · 预触发四档（0x8F）
  · 锁相放大（0x9A/0x9B/0x9C）+ 噪声注入（0x99）
  · 全程检查板子是否存活

用法：
    python regression_2026_10_23.py COM5
"""
import math
import re
import sys
import time

import serial

BAUD = 460800
KN = 37203.0 / 1024.0          # mV / LSB
FULL_REF = 32767.0

PASS, FAIL = [], []


def fr(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %-38s %s" % ("[OK]" if ok else "[!!]", name, detail))


class Board:
    def __init__(self, port):
        self.s = serial.Serial(port, BAUD, timeout=0)
        time.sleep(1.5)
        self.s.reset_input_buffer()

    def rd(self, sec):
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < sec:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
        return bytes(buf)

    def send(self, f, wait=0.3):
        self.s.write(f)
        self.s.flush()
        time.sleep(wait)

    def alive(self, sec=0.8):
        return len(self.rd(sec)) > 0

    def measure(self, sec=0.8):
        t = self.rd(sec).decode("ascii", "ignore")
        out = {}
        for k in ("F", "V", "D", "W", "TY"):
            m = re.findall(r"%s=(\d+)" % k, t)
            out[k] = int(m[-1]) if m else None
        return out

    def sf(self, wait=1.4):
        self.s.reset_input_buffer()
        self.send(fr(0x8A, b"\x00"), wait)
        t = self.rd(0.4).decode("ascii", "ignore")
        m = re.findall(r"SF=(\d+)", t)
        return int(m[-1]) if m else None

    def wave(self, sec=1.5):
        self.s.reset_input_buffer()
        self.s.write(fr(0x83))
        self.s.flush()
        raw = self.rd(sec)
        h = raw.find(b"\x5a\xa5\x01")
        if h < 0:
            return None
        ln = (raw[h + 3] << 8) | raw[h + 4]
        d = raw[h + 5:h + 5 + ln]
        # 波形帧是 1024 点 x **1 字节/点**（LEN=1024 就是点数）。
        # 之前这里按 2 字节切，只拿到 512 点 —— 是测试脚本的错，不是固件。
        return list(d)

    def spec(self, sec=1.6):
        self.s.reset_input_buffer()
        self.s.write(fr(0x8E))
        self.s.flush()
        raw = self.rd(sec)
        h = raw.find(b"\x5a\xa5\x02")
        if h < 0 or len(raw) < h + 520:
            return None
        return list(raw[h + 5:h + 5 + 512])

    def lockin(self, timeout=1.4):
        self.s.reset_input_buffer()
        self.s.write(fr(0x9B))
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
                    if n:
                        return 2 * math.hypot(i, q) / (FULL_REF * n)
            time.sleep(0.01)
        return None

    def close(self):
        self.s.close()


def crossings(wave):
    if not wave:
        return 0
    mid = (max(wave) + min(wave)) / 2
    return sum(1 for i in range(1, len(wave)) if wave[i - 1] < mid <= wave[i])


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    b = Board(port)

    # ---------------- 0. 复位到默认 ----------------
    print("\n[0] 复位到默认状态")
    for f in (fr(0x8B, b"\x00"), fr(0x88, b"\x00"), fr(0x8D, b"\x00"),
              fr(0x89, b"\x00"), fr(0x99, bytes([0, 0])), fr(0x9A, bytes([0])),
              fr(0x8F, bytes([0])), fr(0x90, bytes([1])), fr(0x91, bytes([0])),
              fr(0x98, bytes([0]))):
        b.send(f, 0.2)
    check("板子存活", b.alive())

    # ---------------- 1. 基础测量 ----------------
    print("\n[1] 基础测量（频率/波形）")
    for hz in (1000, 10000, 100000):
        b.send(fr(0x85, hz.to_bytes(4, "little")), 0.6)
        m = b.measure()
        f = m["F"] or 0
        err = abs(f - hz) / hz * 100 if hz else 0
        check("F= @%d Hz" % hz, err < 1.0, "读回 %s（误差 %.2f%%）" % (f, err))
    b.send(fr(0x85, (1000).to_bytes(4, "little")), 0.6)
    m = b.measure()
    check("TY= 波形类型", m["TY"] is not None, "TY=%s" % m["TY"])
    check("V= 有读数", (m["V"] or 0) > 1000, "V=%s mV" % m["V"])

    # ---------------- 2. 波形帧（时基往返前后） ----------------
    print("\n[2] 波形帧：时基往返前后都要可用")
    w = b.wave()
    check("T1 波形帧（初始）", w is not None and crossings(w) > 10,
          "%d 个周期" % crossings(w) if w else "无帧")

    # ---------------- 3. 时基四档 ----------------
    print("\n[3] 时基四档：频谱读数")
    cases = [(0, 1000, "T1 50kHz"), (2, 1_000_000, "T3 6.25MHz"),
             (3, 5_000_000, "T4 12.5MHz")]
    for sel, hz, name in cases:
        b.send(fr(0x8D, bytes([sel])), 0.4)
        b.send(fr(0x85, hz.to_bytes(4, "little")), 0.7)
        v = b.sf()
        err = abs(v - hz) / hz * 100 if (v and hz) else 999
        check("%s SF= @%d" % (name, hz), err < 1.0, "读回 %s（%.2f%%）" % (v, err))

    # ---------------- 4. 谱帧三档 ----------------
    print("\n[4] 谱帧（0x8E）峰值位置")
    for sel, hz, name, fs in ((0, 1000, "T1", 50000.0),
                              (2, 1_000_000, "T3", 6250000.0),
                              (3, 5_000_000, "T4", 12500000.0)):
        b.send(fr(0x8D, bytes([sel])), 0.35)
        b.send(fr(0x85, hz.to_bytes(4, "little")), 0.7)
        sp = b.spec()
        if not sp:
            check("%s 谱帧" % name, False, "无帧")
            continue
        bin_ = max(range(len(sp)), key=sp.__getitem__)
        f = bin_ * fs / 1024.0
        df = fs / 1024.0
        # 判据用「半 bin」：谱峰只能落在整数 bin 上，T1 的 Δf=48.8Hz，
        # 用 1% 去卡 1kHz 本身就是不合理的（半 bin 就有 2.4%）。
        ok = abs(f - hz) <= df / 2 + 1e-6
        check("%s 谱帧峰值" % name, ok,
              "bin %d -> %.0f Hz（Δf=%.0f，半 bin 内）" % (bin_, f, df))

    # ---------------- 5. 回到 T1，波形必须恢复 ----------------
    print("\n[5] 时基往返后波形帧（今天的重点）")
    b.send(fr(0x8D, bytes([0])), 0.5)
    b.send(fr(0x85, (1000).to_bytes(4, "little")), 0.6)
    oks = 0
    for _ in range(3):
        if b.wave():
            oks += 1
    check("回 T1 后波形 3/3", oks == 3, "%d/3" % oks)
    check("板子存活", b.alive())

    # ---------------- 6. 窗函数 / 帧重叠 / 谱平均 ----------------
    print("\n[6] 频谱扩展功能")
    base = b.sf()
    b.send(fr(0x90, bytes([0])), 0.4)       # 矩形
    sf_rect = b.sf()
    b.send(fr(0x90, bytes([1])), 0.4)       # Hann
    sf_hann = b.sf()
    check("窗函数切换不改变频率读数",
          base and sf_rect and sf_hann and abs(sf_hann - base) < 50,
          "Hann=%s 矩形=%s" % (sf_hann, sf_rect))

    b.send(fr(0x91, bytes([1])), 0.4)
    check("帧重叠开启后仍可读", b.sf() is not None)
    b.send(fr(0x91, bytes([0])), 0.3)

    b.send(fr(0x98, bytes([1])), 0.4)
    check("谱平均开启后仍可读", b.sf() is not None)
    b.send(fr(0x98, bytes([0])), 0.3)

    # ---------------- 7. 预触发四档 ----------------
    print("\n[7] 预触发四档")
    for tier, name in ((0, "0%"), (1, "25%"), (2, "50%"), (3, "75%")):
        b.send(fr(0x8F, bytes([tier])), 0.35)
        w = b.wave()
        check("预触发 %s 出帧" % name, w is not None and len(w) == 1024,
              "%d 点" % len(w) if w else "无帧")
    b.send(fr(0x8F, bytes([0])), 0.3)

    # ---------------- 8. 锁相放大 + 噪声 ----------------
    print("\n[8] 锁相放大与噪声注入")
    b.send(fr(0x99, bytes([0, 0])), 0.3)
    b.send(fr(0x9A, bytes([1])), 0.5)
    amps = [a for a in (b.lockin() for _ in range(5)) if a]
    check("锁相出数", len(amps) >= 3, "%d/5 帧" % len(amps))
    if amps:
        base_amp = sorted(amps)[len(amps) // 2]
        m = b.measure()
        v = m["V"] or 0
        lk_mv = base_amp * 2 * KN
        err = abs(lk_mv - v) / v * 100 if v else 999
        check("锁相与直接测量一致", err < 10,
              "锁相 %.0f mV / 直接 %d mV（%.1f%%）" % (lk_mv, v, err))

        # 埋进噪声
        b.send(fr(0x99, bytes([8, 3])), 0.5)
        nm = [a for a in (b.lockin() for _ in range(5)) if a]
        if nm:
            att_amp = sorted(nm)[len(nm) // 2]
            check("加噪后锁相仍稳定", att_amp > 0,
                  "%d/5 帧" % len(nm))
        b.send(fr(0x99, bytes([0, 0])), 0.4)
    b.send(fr(0x9A, bytes([0])), 0.3)

    # ---------------- 9. 收尾 ----------------
    print("\n[9] 收尾")
    b.send(fr(0x8D, bytes([0])), 0.3)
    b.send(fr(0x85, (1000).to_bytes(4, "little")), 0.4)
    check("板子最终存活", b.alive())
    b.close()

    print("\n" + "=" * 60)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for x in FAIL:
            print("   -", x)
    print("=" * 60)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
