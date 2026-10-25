# -*- coding: utf-8 -*-
"""传感器接入诊断：为什么要这个脚本。

现象：接上麦克风模块后，Vpp 一直是 1500 mV 左右，
      加不加声音都不变，**连没声音也是 1500**。

这个"没声音也有 1500"几乎可以排除麦克风 —— 麦克风没声时应该是 0。
所以要先弄清楚：这个 1500 到底是什么东西。

判据（一跑就知道）：

    看平均值（DC 偏置）
        约 162 码 = 1.25V  ->  麦克风的直流偏置进来了，模块确实接着
        约 128 码 = 0V     ->  没有直流，说明信号不是从模块来的

    看估算频率
        约 50 Hz   ->  工频干扰（导线拾取的市电），这才是 1500mV 的来源
        约 1 kHz   ->  回环飞线还插着，DDS 的信号
        杂乱无周期 ->  宽带噪声

    看波形前几十点
        缓慢起伏一个大波浪 -> 工频
        密集的多个周期     -> 1kHz 左右

用法：
    先关掉上位机 GUI（它占串口），然后
    python diag_sensor.py
    python diag_sensor.py COM5
"""
import math
import re
import sys
import time

import serial

from port_pick import pick_port

LSB = 36.33


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


def read_wave(s):
    """请求一帧 1024 点波形，返回码值列表。"""
    s.reset_input_buffer()
    s.write(frame(0x83, b"\x00"))   # 0x83 请求波形，负载 0x00（见 protocol.py）
    s.flush()

    buf = drain(s, 0.9)
    head = buf.find(b"\x5a\xa5\x01")
    if head < 0 or len(buf) < head + 5:
        return None

    ln = (buf[head + 3] << 8) | buf[head + 4]
    if ln < 64 or len(buf) < head + 5 + ln:
        return None
    return list(buf[head + 5:head + 5 + ln])


def estimate_freq(codes, fs=50000.0):
    """用过零次数估频率。先去掉直流。"""
    mean = sum(codes) / len(codes)
    x = [c - mean for c in codes]
    amax = max(abs(v) for v in x)
    if amax < 3:          # 幅度太小，全是噪，估不了
        return None, mean, amax
    thr = amax * 0.25     # 带迟滞，避免噪声反复穿越
    crossings = 0
    state = 1 if x[0] > 0 else -1
    for v in x:
        if state > 0 and v < -thr:
            crossings += 1
            state = -1
        elif state < 0 and v > thr:
            crossings += 1
            state = 1
    if crossings < 2:
        return None, mean, amax
    # 一帧 N 点，过零次数 crossings 对应 crossings/2 个周期
    cycles = crossings / 2.0
    return cycles * fs / len(codes), mean, amax


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    if port is None:
        return 1
    try:
        s = serial.Serial(port, 460800, timeout=0)
    except Exception as e:
        print("[错误] 打不开 %s" % port)
        print("       上位机 GUI 还开着？先关掉它再跑这个脚本。")
        print("       (%s)" % str(e)[:70])
        return 1

    time.sleep(1.0)
    s.reset_input_buffer()

    print("=" * 70)
    print("  传感器接入诊断")
    print("=" * 70)
    print()

    # 顺带读一次测量行，拿 F 和 V
    s.write(frame(0x8D, b"\x00"))    # T1
    s.flush()
    time.sleep(0.3)
    txt = drain(s, 0.5).decode("ascii", "ignore")
    f_m = re.findall(r"F=(\d+)", txt)
    v_m = re.findall(r"V=(\d+)", txt)
    if f_m or v_m:
        print("  板子自报：F = %s Hz    V = %s mV"
              % (f_m[-1] if f_m else "--", v_m[-1] if v_m else "--"))
        print()

    codes = read_wave(s)
    if not codes:
        print("  [错误] 没收到波形帧。")
        print("         检查：① 板子是否在跑（上电后 1 秒开始出数）")
        print("               ② 串口是否被别的程序占用")
        s.close()
        return 1

    n = len(codes)
    mean = sum(codes) / n
    mn, mx = min(codes), max(codes)
    vpp = (mx - mn) * LSB
    dc_mv = (mean - 128) * LSB
    freq, _, amp = estimate_freq(codes)

    print("  波形帧 %d 点（T1 = 50 kHz 采样，一帧 %.1f ms）" % (n, n / 50.0))
    print()
    print("  峰峰值      %4d mV   （码 %d ~ %d，跨度 %d 码）" % (vpp, mn, mx, mx - mn))
    print("  平均值      %4d mV   （码 %.0f，即直流偏置）" % (dc_mv, mean))
    print("  估算频率    %s" % ("估不出（无周期性）" if freq is None else "%.0f Hz" % freq))
    print()

    # ---- 波形缩略图 ----
    print("  波形形状（每行 64 点，竖轴 = 码值）：")
    step = max(1, n // 256)
    sample = codes[::step][:256]
    for row in range(0, len(sample), 64):
        chunk = sample[row:row + 64]
        line = ""
        for c in chunk:
            lvl = (c - mn) / max(1, mx - mn)
            line += " ▁▂▃▄▅▆▇█"[min(8, int(lvl * 8))]
        print("    " + line)
    print()

    # ---- 判断 ----
    print("=" * 70)
    print("  判断")
    print("=" * 70)
    print()

    if vpp < 60:
        print("  ✗ 几乎没有信号（Vpp < 60 mV）")
        print("    麦克风可能没接上，或模块没供电。")
    elif mean > 140:
        print("  ✓ 平均值 %.0f 码 ≈ %.2f V，说明**麦克风的直流偏置进来了**，"
              % (mean, mean * LSB / 1000))
        print("    模块确实接在 AD 上。")
    elif mean < 138:
        print("  ⚠ 平均值 %.0f 码 ≈ 0 V，**没有看到麦克风的 1.25V 偏置**。"
              % mean)
        print("    说明这个信号不是从麦克风模块来的 ——")
        print("    要么模块没接对，要么串了隔直电容，要么是导线感应的干扰。")
    print()

    if freq is not None:
        if 40 <= freq <= 65:
            print("  ★ 频率 %.0f Hz —— 这是**工频干扰**。" % freq)
            print("    50Hz 的干扰盖过了麦克风信号（麦克风通常只有几百毫伏）。")
            print("    这就是'没声音也 1500mV'的原因。")
            print()
            print("    对策（按有效性排序）：")
            print("      1. 麦克风输出串一只 1µF ~ 10µF 隔直/隔干扰电容")
            print("      2. 把模块的线剪短，最好用屏蔽线")
            print("      3. 模块 GND 用短线接到板子 GND（地环路越小越好）")
            print("      4. 麦克风模块远离电源线和手机")
        elif 900 <= freq <= 1100:
            print("  ★ 频率 %.0f Hz —— 这是 **DDS 的 1kHz**。" % freq)
            print("    回环飞线还插着！拔掉 DA→AD 那根线。")
        elif freq > 2000:
            print("  ★ 频率 %.0f Hz —— 高频成分，可能是开关电源噪声或混叠。" % freq)
        else:
            print("  ★ 频率 %.0f Hz —— 不是工频也不是 1kHz，看看波形形状再判断。" % freq)
    else:
        print("  ★ 波形没有明显周期性 —— 可能是宽带噪声，或信号太弱被噪声淹没。")

    print()
    s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
