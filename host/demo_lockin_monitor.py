# -*- coding: utf-8 -*-
"""锁相演示用的实时监视器 —— 录制时开这个，一边操作一边看三个数怎么变。

和 demo_sensor.py 的区别
------------------------
那个是"一次跑完、最后出汇总表"的脚本，适合验证；
这个是**持续刷新的看板**，适合录制和现场演示 ——
你要一边拉远距离、一边加噪声、一边开锁相，眼睛得一直盯着读数。

屏幕上是三行：

    频率    F = 1002 Hz          波动 ±   3 Hz
    峰峰值  V = 1823 mV          波动 ± 245 mV      <- 这一行会乱跳
    锁相    L =  421 mV          波动 ±   6 mV      <- 这一行很稳

**"波动"这一列就是演示的全部看点。** 话说得再好，不如让评委看两个数一起跳。

用法
----
    python demo_lockin_monitor.py            # 自动找串口
    python demo_lockin_monitor.py COM5

    按  S  记一次快照（录制时用来做对比表）
    按  L  切换锁相开/关
    按  Q  退出
"""
import math
import os
import re
import statistics
import sys
import time

import serial

from port_pick import pick_port

KN = 36.33              # mV/LSB，标定值（cmd_decoder.v 的 KN_DEF=37203）
FULL_REF = 32767.0      # 锁相 I/Q 满量程
FREQ_HZ = 1000          # 演示用的声源频率，也是锁相参考频率
WINDOW = 12             # 波动统计窗口（最近 12 次）


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


class Rig:
    def __init__(self, port):
        self.s = serial.Serial(port, 460800, timeout=0)
        time.sleep(1.2)
        self.s.reset_input_buffer()

    def send(self, data, wait=0.18):
        self.s.write(data)
        self.s.flush()
        time.sleep(wait)

    def drain(self, sec):
        buf = bytearray()
        t0 = time.time()
        while time.time() - t0 < sec:
            n = self.s.in_waiting
            if n:
                buf += self.s.read(n)
            else:
                time.sleep(0.004)
        return bytes(buf)

    def read_vpp(self, sec=0.30):
        """读最近一条测量行里的 F 和 V。"""
        text = self.drain(sec).decode("ascii", "ignore")
        f = re.findall(r"F=(\d+)", text)
        v = re.findall(r"V=(\d+)", text)
        return (int(f[-1]) if f else None, int(v[-1]) if v else None)

    def read_lockin(self):
        """请求一帧 I/Q 并换算成幅度（mV，模块输入端口径）。"""
        self.s.reset_input_buffer()
        self.s.write(frame(0x9B))
        self.s.flush()
        raw = self.drain(0.42)
        head = raw.find(b"\x5a\xa5\x03")
        if head < 0 or len(raw) < head + 22:
            return None
        body = raw[head:head + 22]
        i_val = int.from_bytes(body[5:11], "little", signed=True)
        q_val = int.from_bytes(body[11:17], "little", signed=True)
        cnt = int.from_bytes(body[17:21], "little")
        if not cnt:
            return None
        # 与 demo_sensor.py 同一口径：幅度 = 2*|IQ| / (满量程*N) * 2 * KN
        return 2.0 * math.hypot(i_val, q_val) / (FULL_REF * cnt) * 2.0 * KN


def spread(values):
    """波动幅度 = 最大值 − 最小值。空集返回 None。"""
    v = [x for x in values if x is not None]
    if len(v) < 2:
        return None
    return max(v) - min(v)


def bar(value, full, width=26):
    """把「波动」画成横条，越长越不稳定。

    一开始画的是读数的绝对值，结果 Vpp 和锁相的条一样长 ——
    看起来"两个都差不多"，恰恰抹掉了要表达的东西。
    改成画波动：Vpp 那条长，锁相那条短，一眼就能看出差别。
    """
    if value is None:
        return " " * width
    n = int(round(value / max(1e-9, full) * width))
    n = max(0, min(width, n))
    return "█" * n + "·" * (width - n)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    if port is None:
        return 1

    rig = Rig(port)

    # ---- 初始化：1kHz 正弦、T1、关噪声（对外部信号无效，但保持默认）、开锁相 ----
    rig.send(frame(0x8B, b"\x00"))                       # 停扫频
    rig.send(frame(0x8D, b"\x00"))                       # T1
    rig.send(frame(0x85, FREQ_HZ.to_bytes(4, "little")))  # 锁相参考 1kHz
    rig.send(frame(0x9C, bytes([32, 0])))                # 积分 32 周期
    rig.send(frame(0x9A, b"\x01"))                       # 开锁相
    time.sleep(0.6)

    lk_on = True
    hist_v, hist_l, hist_f = [], [], []
    snaps = []

    while True:
        f, v = rig.read_vpp(0.26)
        lk = rig.read_lockin() if lk_on else None
        if f is not None:
            hist_f.append(f)
        if v is not None:
            hist_v.append(v)
        if lk is not None:
            hist_l.append(lk)
        for h in (hist_f, hist_v, hist_l):
            del h[:-WINDOW]

        clear()
        print("=" * 74)
        print("  WaveCore  锁相放大演示监视器        （按 S 快照 / L 开关锁相 / Q 退出）")
        print("=" * 74)
        print()

        f_med = int(statistics.median(hist_f)) if hist_f else None
        v_med = int(statistics.median(hist_v)) if hist_v else None
        l_med = int(statistics.median(hist_l)) if hist_l else None

        # 先算出两组波动，两条横条用同一个标尺，才比得出来
        sv = spread(hist_v)
        sl = spread(hist_l)
        scale = max(20.0, sv or 0.0, sl or 0.0)

        print("  频率      F = %6s Hz      波动 ± %4s Hz"
              % ("--" if f_med is None else f_med,
                 "--" if spread(hist_f) is None else int(spread(hist_f) / 2)))
        print("  峰峰值    V = %6s mV      波动 ± %4s mV    %s"
              % ("--" if v_med is None else v_med,
                 "--" if sv is None else int(sv / 2),
                 bar(sv, scale)))
        print("  锁相      L = %6s mV      波动 ± %4s mV    %s"
              % ("--" if (not lk_on or l_med is None) else l_med,
                 "--" if (not lk_on or sl is None) else int(sl / 2),
                 "已关闭" if not lk_on else bar(sl, scale)))
        print("                                            └─ 横条长度 = 波动大小，同一个标尺")
        print()

        # 判据：Vpp 波动是锁相波动的几倍
        if lk_on and sv and sl and sl > 0.5:
            ratio = sv / sl
            print("  稳定度对比：Vpp 波动是锁相的 %.1f 倍" % ratio)
            if ratio >= 5:
                print("  ✓ 这个比值就是演示要看的东西 —— 越大越有说服力")
            else:
                print("   信号还不够弱。试试：拉远 / 在旁边加噪声 / 关小声源")
        elif lk_on and sv and (sl is None or sl <= 0.5):
            print("  锁相读数非常稳（波动 < 1mV）")
        print()
        print("-" * 74)

        if snaps:
            print()
            print("  快照：")
            print("    #    F(Hz)      Vpp(mV)     锁相(mV)     锁相/Vpp")
            for i, (sf, svv, slk) in enumerate(snaps, 1):
                r = "--" if not slk or not svv else "%.2f" % (slk / svv)
                print("    %-4d %-10s %-12s %-12s %s"
                      % (i, "--" if sf is None else sf,
                         "--" if svv is None else svv,
                         "--" if slk is None else int(slk), r))

        print()
        print("  " + "-" * 68)
        print("  提示：Vpp 会跟着距离变，锁相不会 —— 因为锁相按频率挑，不按峰值判。")

        # 非阻塞按键
        try:
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    k = msvcrt.getwch().lower()
                    if k == "q":
                        break
                    elif k == "s":
                        snaps.append((f_med, v_med, lk))
                    elif k == "l":
                        lk_on = not lk_on
                        rig.send(frame(0x9A, b"\x01" if lk_on else b"\x00"))
                        hist_l.clear()
            else:
                time.sleep(0.05)
        except Exception:
            pass

        time.sleep(0.05)

    rig.send(frame(0x9A, b"\x00"))
    rig.s.close()
    print("\n  已关闭锁相，串口已释放。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
