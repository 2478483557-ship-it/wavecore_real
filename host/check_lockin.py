# -*- coding: utf-8 -*-
"""锁相算得对不对 —— 用已知幅度的信号验证。

为什么要这个脚本
----------------
"锁相真的做对了吗"这个问题，靠读代码回答不了，得让它算一个已知答案。

做法很简单：**用板内回环**。
DDS 产生 1kHz 正弦 → DAC → 模拟链路 → ADC，这条路上的信号幅度
测量模块自己会报（V= 那一栏，单位 mV，Vpp 口径）。
锁相读出来的**也应该是 Vpp 口径**。两个数应该接近。

判据：

    锁相 / Vpp
      0.90 ~ 1.10    -> 算对了
      1.8  ~ 2.2     -> 口径取成了幅值没除 2（差一倍）
      0.45 ~ 0.55    -> 口径取成了幅值的一半
      乱跳 / 为 0    -> 参考频率没对上，或没开使能

同时验证积分周期：把 32 改成 128，读数应该更稳（波动更小），
但**均值不该变** —— 变了说明有直流泄漏或整周期没凑齐。

用法：
    python check_lockin.py
    python check_lockin.py COM5
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


def drain(s, sec):
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < sec:
        n = s.in_waiting
        if n:
            buf += s.read(n)
        else:
            time.sleep(0.004)
    return bytes(buf)


def read_pair(s, periods):
    """读一次 (Vpp 读数, 锁相读数)。"""
    s.reset_input_buffer()
    text = drain(s, 0.26).decode("ascii", "ignore")
    v = re.findall(r"V=(\d+)", text)
    vpp = int(v[-1]) if v else None

    s.write(frame(0x9B))
    s.flush()
    raw = drain(s, 0.44)
    head = raw.find(b"\x5a\xa5\x03")
    lk = None
    if head >= 0 and len(raw) >= head + 22:
        b = raw[head:head + 22]
        i_val = int.from_bytes(b[5:11], "little", signed=True)
        q_val = int.from_bytes(b[11:17], "little", signed=True)
        cnt = int.from_bytes(b[17:21], "little")
        if cnt:
            lk = 2.0 * math.hypot(i_val, q_val) / (FULL_REF * cnt) * 2.0 * KN
    return vpp, lk


def sample(s, periods, n=8):
    vs, ls = [], []
    for _ in range(n):
        v, l = read_pair(s, periods)
        if v is not None:
            vs.append(v)
        if l is not None:
            ls.append(l)
        time.sleep(0.12)
    return vs, ls


def stat(values):
    if not values:
        return None, None
    if len(values) < 2:
        return values[0], 0.0
    return statistics.median(values), (max(values) - min(values)) / 2


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    if port is None:
        return 1
    try:
        s = serial.Serial(port, 460800, timeout=0)
    except Exception as e:
        print("[错误] 打不开 %s —— 上位机 GUI 还开着？先关掉。" % port)
        print("       (%s)" % str(e)[:60])
        return 1

    time.sleep(1.0)
    s.reset_input_buffer()

    print("=" * 68)
    print("  锁相精度自检（回环，已知幅度）")
    print("=" * 68)
    print()

    # 准备：1kHz 正弦、T1、停扫频、开锁相
    s.write(frame(0x8B, b"\x00"))      # 停扫频
    time.sleep(0.15)
    s.write(frame(0x8D, b"\x00"))      # T1
    time.sleep(0.15)
    s.write(frame(0x85, FREQ_HZ.to_bytes(4, "little")))   # 1kHz，也是锁相参考
    time.sleep(0.15)
    s.write(frame(0x88, b"\x00"))      # 正弦
    time.sleep(0.15)
    s.write(frame(0x9C, bytes([32, 0])))     # 积分 32 周期
    time.sleep(0.15)
    s.write(frame(0x9A, b"\x01"))      # 开锁相
    time.sleep(0.8)

    print("  已设：1kHz 正弦，T1，积分 32 周期，锁相开启")
    print()

    # ---- 第一组：积分 32 ----
    vs32, ls32 = sample(s, 32)
    v32, vd32 = stat(vs32)
    l32, ld32 = stat(ls32)

    print("  积分 32 周期（T = 32 ms，带宽 15.6 Hz）")
    if v32 is None or l32 is None:
        print("    ✗ 没读到数据。检查板子是否在跑、串口是否被占。")
        s.close()
        return 1
    print("    Vpp 读数    %5.0f ± %3.0f mV" % (v32, vd32))
    print("    锁相读数    %5.0f ± %3.0f mV" % (l32, ld32))
    ratio32 = l32 / v32 if v32 else 0
    print("    比值        %.3f" % ratio32)
    print()

    # ---- 第二组：积分 128 ----
    s.write(frame(0x9C, bytes([128, 0])))
    time.sleep(0.6)
    vs128, ls128 = sample(s, 128)
    v128, vd128 = stat(vs128)
    l128, ld128 = stat(ls128)

    print("  积分 128 周期（T = 128 ms，带宽 3.9 Hz）")
    print("    Vpp 读数    %5.0f ± %3.0f mV" % (v128, vd128))
    print("    锁相读数    %5.0f ± %3.0f mV" % (l128, ld128))
    ratio128 = l128 / v128 if v128 else 0
    print("    比值        %.3f" % ratio128)
    print()

    # ---- 结论 ----
    print("=" * 68)
    print("  结论")
    print("=" * 68)
    print()

    ok = True
    if 0.90 <= ratio32 <= 1.10:
        print("  ✓ 口径正确：锁相读数 ≈ Vpp 读数（比值 %.2f）" % ratio32)
    elif 1.80 <= ratio32 <= 2.20:
        print("  ✗ 比值约 2 —— 口径把幅值当 Vpp 了，少除一次 2")
        ok = False
    elif 0.45 <= ratio32 <= 0.55:
        print("  ✗ 比值约 0.5 —— 口径只取了一半")
        ok = False
    else:
        print("  ? 比值 %.2f 不在预期范围，看下面的稳定性再判断" % ratio32)
        ok = False

    # 积分周期的影响：均值不该变太多，波动应该变小
    if l32 and l128:
        drift = abs(l128 - l32) / l32 * 100
        if drift < 5:
            print("  ✓ 积分周期 32 -> 128，均值只变了 %.1f%%（应该基本不变）" % drift)
        else:
            print("  ? 积分周期 32 -> 128，均值变了 %.1f%% —— 偏大" % drift)
            print("    可能原因：整周期没凑齐（参考频率与实际信号不是严格同频）")
            ok = False

        if ld32 and ld128:
            print("  %s 波动：32 周期 ±%.1f mV -> 128 周期 ±%.1f mV"
                  % ("✓" if ld128 <= ld32 else "?", ld32, ld128))
            if ld128 <= ld32:
                print("    积分越久越稳，符合预期（带宽变窄 4 倍）")
            else:
                print("    积分越久反而更飘？可能是信号源本身在漂（DDS 温漂）")

    print()
    if ok:
        print("  → 锁相算得对，可以放心演示。")
    else:
        print("  → 上面有异常项，把整段输出发我。")
    print()

    s.write(frame(0x9A, b"\x00"))
    s.write(frame(0x9C, bytes([32, 0])))
    s.flush()
    s.close()
    print("  已关闭锁相，积分周期恢复 32。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
