# -*- coding: utf-8 -*-
"""
verify_hann_window.py —— 验证"自研 FFT 加 Hann 窗"这个改动的效果。

为什么写它：本机跑不了 xsim（环境限制，已多次证实），而这次改的正是"仿真抓不到"的
窗泄漏问题。所以按 SK-034 的套路，用**数值模型**把板上的三个读数(SF/S2/S3)直接算出来，
并与"未加窗"对照，看假峰是否消失、真谐波是否原样保留。

做法（刻意贴近 RTL，而不是"随便做个 FFT"）：
  1. 窗表**从 RTL 用的同一份 src/hann_1024.hex 读**（不看公式，避免表错 -> SK-024 的教训）
  2. 输入按 ADC 偏移二进制量化成 8bit 码
  3. 加窗严格按 RTL 的整数运算: s = code-128; v = (s*w) >> 7   (算术右移=向下取整, 同 Verilog >>>)
  4. 找峰严格按 RTL 的判据: 只看 bin1~511 / GAP=6 bin / 幅度门限 m >= 主峰>>3 / 三趟扫描
  5. 幅度用 L1 范数 |re|+|im|（RTL 就是这么做的，不是 sqrt）
用法: python verify_hann_window.py
"""
import cmath
import math
import os

ROOT = r"C:\Users\Lenovo\WorkBuddy\2026-09-02-11-10-14\wavecore"
N = 1024
FS = 50000.0
DF = FS / N                      # 48.828125 Hz/bin
GAP = 6                          # self_fft_1024.v 的 localparam GAP


def load_hann():
    """从 RTL 用的同一份 hex 读窗表(Q15)。"""
    p = os.path.join(ROOT, "src", "hann_1024.hex")
    vals = [int(x, 16) for x in open(p, encoding="ascii").read().split()]
    assert len(vals) == N, "窗表长度 %d != %d" % (len(vals), N)
    return vals


def fft(a):
    """迭代 radix-2 FFT（纯 Python，够用）。"""
    n = len(a)
    j = 0
    a = list(a)
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    ln = 2
    while ln <= n:
        ang = -2j * math.pi / ln
        wl = cmath.exp(ang)
        for i in range(0, n, ln):
            w = 1 + 0j
            for k in range(i, i + ln // 2):
                u = a[k]
                v = a[k + ln // 2] * w
                a[k] = u + v
                a[k + ln // 2] = u - v
                w *= wl
        ln <<= 1
    return a


def adc_sine(freq, amp=127.0, phase=0.0):
    """8bit 偏移二进制 ADC 采样（正弦）。freq 不是整数 bin 也没关系——这正是要测的。"""
    out = []
    for i in range(N):
        v = 128.0 + amp * math.sin(2 * math.pi * freq * i / FS + phase)
        out.append(max(0, min(255, int(round(v)))))
    return out


def adc_square(freq, lo, hi):
    """理想方波(50% 占空)在 ADC 侧量化后的样子。"""
    out = []
    for i in range(N):
        ph = (freq * i / FS) % 1.0
        out.append(hi if ph < 0.5 else lo)
    return out


def windowed(codes, hann, use_hann=True):
    """严格按 RTL 的整数运算做加窗。返回喂给 FFT 的实数序列。"""
    out = []
    for c, w in zip(codes, hann):
        s = c - 128                       # 中点归零补码
        if use_hann:
            # Verilog: win_p = s * $signed({1'b0,w});  win_o = win_p[22:7]
            # 即 (s*w) >> 7，算术右移 = 向下取整（Python >> 对负数同样是向下取整）
            out.append((s * w) >> 7)
        else:
            out.append(s << 8)            # 原来的 din[31:16] = s<<8
    return out


def find_peaks(seq, gap=GAP):
    """完全复刻 self_fft_1024.v 的三趟扫描 + GAP + 门限。"""
    X = fft(seq)
    mag = [abs(X[k].real) + abs(X[k].imag) for k in range(N)]   # L1 范数, 同 RTL
    pk_bin = b2 = b3 = 0
    pk_best = m2 = m3 = 0.0
    for scan in range(3):
        best = -1.0
        bb = -1
        for k in range(1, 512):           # 只看正半轴, 跳过直流
            d = mag[k]
            if scan == 0:
                ok = True
            elif scan == 1:
                ok = abs(k - pk_bin) >= gap
            else:
                ok = abs(k - pk_bin) >= gap and abs(k - b2) >= gap
            if ok and d > best:
                best = d
                bb = k
        if scan == 0:
            pk_best, pk_bin = best, bb
        elif scan == 1:
            m2, b2 = best, bb
        else:
            m3, b3 = best, bb
    gate = pk_best / 8.0                  # RTL 是整数 pk_best>>3, 这里用 /8 近似
    f1 = (pk_bin * 50000) >> 10
    f2 = ((b2 * 50000) >> 10) if m2 >= gate else 0
    f3 = ((b3 * 50000) >> 10) if m3 >= gate else 0
    return dict(SF=f1, S2=f2, S3=f3, pk_bin=pk_bin, b2=b2, b3=b3,
                m2_ratio=m2 / pk_best if pk_best else 0,
                m3_ratio=m3 / pk_best if pk_best else 0,
                leak24=mag[24] / pk_best if pk_best else 0)


def main():
    hann = load_hann()
    print("窗表: src/hann_1024.hex  n=%d  min=%d  max=%d (Q15, 峰值应=32768)"
          % (len(hann), min(hann), max(hann)))
    print("bin 宽 = %.3f Hz  |  GAP = %d bin  |  幅度门限 = 主峰/8 = 12.5%%\n" % (DF, GAP))

    # ---------- 1) 正弦 1kHz: 小数 bin 20.480（上板实测 S2 曾 = 1171Hz 的那个场景）----------
    print("=" * 78)
    print("【1】1kHz 正弦（1000/48.828 = bin 20.480，非整数 —— 假峰就出在这里）")
    print("=" * 78)
    print("做三组对照，其中 GAP=4+矩形窗 必须**复现出板上实测的 S2=1171Hz(bin24)**，")
    print("以此证明这个数值模型是可信的（能复现已知故障），再看加窗的效果。\n")
    print("%-30s %-9s %-9s %-9s %-10s %s" % ("工况", "SF(Hz)", "S2(Hz)", "S3(Hz)", "bin24/主峰", "判定"))
    worst = {}
    for gap in (4, 6):
        for label, uh in (("矩形窗", False), ("Hann窗", True)):
            wr = 0.0
            hit = []
            for ph_deg in range(0, 360, 15):
                codes = adc_sine(1000.0, phase=math.radians(ph_deg))
                r = find_peaks(windowed(codes, hann, use_hann=uh), gap=gap)
                wr = max(wr, r["leak24"])
                if r["S2"] != 0:
                    hit.append((ph_deg, r["S2"], r["b2"]))
            key = "GAP=%d + %s" % (gap, label)
            worst[key] = (wr, hit)
            tag = "❌ 报假峰 %d 次/24 相位" % len(hit) if hit else "✅ 一次都没报"
            sample = ""
            if hit:
                sample = "  例: 相位%d° -> S2=%d (bin%d)" % hit[0]
            print("%-30s %-9s %-9s %-9s %-9.1f%% %s%s"
                  % (key, "", "", "", wr * 100, tag, sample))
    print("\n  上板实测对照：GAP=4 + 矩形窗 板子读出 `S2=0001171Hz` == bin24，"
          "本模型同样是 bin%d。" % worst["GAP=4 + 矩形窗"][1][0][2]
          if worst["GAP=4 + 矩形窗"][1] else "  （GAP=4+矩形窗 未复现，需检查模型）")
    print("  bin24 相对主峰: 矩形窗最坏 %.1f%%  vs  Hann 窗最坏 %.1f%%  （幅度门限 12.5%%）"
          % (worst["GAP=4 + 矩形窗"][0] * 100, worst["GAP=4 + Hann窗"][0] * 100))
    print("  -> Hann 窗把越线风险从 %.1f%% 压到 %.1f%%，余量约 %.0f 倍。"
          % (worst["GAP=4 + 矩形窗"][0] * 100, worst["GAP=4 + Hann窗"][0] * 100,
             worst["GAP=4 + 矩形窗"][0] / max(worst["GAP=4 + Hann窗"][0], 1e-9)))

    # ---------- 2) 正弦扫一圈频率，看还有没有残余假峰 ----------
    print("\n" + "=" * 78)
    print("【2】正弦扫频 800~1200Hz（每 10Hz，固定相位40°）: 假峰命中率")
    print("=" * 78)
    for label, gap, uh in (("GAP=4 + 矩形窗(09-30前)", 4, False),
                           ("GAP=6 + 矩形窗(09-30 上午)", 6, False),
                           ("GAP=6 + Hann窗(本次改后)", 6, True),
                           ("GAP=4 + Hann窗(理论最优)", 4, True)):
        bad = []
        for f in range(800, 1201, 10):
            codes = adc_sine(float(f), phase=math.radians(40))
            r = find_peaks(windowed(codes, hann, use_hann=uh), gap=gap)
            if r["S2"] != 0:
                bad.append((f, r["S2"], r["pk_bin"], r["b2"]))
        print("%-26s 报出假峰: %2d / 41 个频点 %s"
              % (label, len(bad), "" if not bad else "  例: " + ", ".join(
                  "%dHz->S2=%d(bin%d)" % (b[0], b[1], b[3]) for b in bad[:5])))

    # ---------- 3) 方波 1kHz: 真谐波必须一根不少 ----------
    print("\n" + "=" * 78)
    print("【3】1kHz 方波（真谐波在 bin61 / bin102）—— 加窗不能把它们弄丢")
    print("=" * 78)
    for label, uh, lo, hi in (
            ("矩形窗(改前, 方波 26/230)", False, 26, 230),
            ("Hann窗(改后, 方波 1/255)", True, 1, 255),
            ("Hann窗 + 旧幅度 26/230", True, 26, 230)):
        codes = adc_square(1000.0, lo, hi)
        r = find_peaks(windowed(codes, hann, use_hann=uh))
        print("%-26s SF=%-6d S2=%-6d S3=%-6d   (bin %d/%d/%d, 二峰比 %.1f%%, 三峰比 %.1f%%)"
              % (label, r["SF"], r["S2"], r["S3"], r["pk_bin"], r["b2"], r["b3"],
                 r["m2_ratio"] * 100, r["m3_ratio"] * 100))

    # ---------- 4) 双音 1k + 1.1k: GAP=6 不能把两峰并成一个 ----------
    print("\n" + "=" * 78)
    print("【4】双音 1000+1100Hz（两峰相隔约 2 bin? 不, 见下）—— 检查 GAP=6 不会并峰")
    print("=" * 78)
    print("  说明: 1000Hz=bin20.48, 1100Hz=bin22.53, 两峰只隔 2 bin,")
    print("        所以本通路的 GAP=6 本来就分不开它们（IP 通路 4096 点才分得开）。")
    print("        这里只确认主峰仍落在 1kHz 附近、且没产生离谱读数：")
    for label, uh in (("矩形窗", False), ("Hann窗", True)):
        codes = [(c1 + c2) // 2 for c1, c2 in
                 zip(adc_sine(1000.0, amp=110.0), adc_sine(1100.0, amp=110.0))]
        r = find_peaks(windowed(codes, hann, use_hann=uh))
        print("        %-8s 双音 -> SF=%d S2=%d S3=%d (bin %d/%d/%d)"
              % (label, r["SF"], r["S2"], r["S3"], r["pk_bin"], r["b2"], r["b3"]))
    print("  注意：合成两峰相距仅 2 bin，两窗都会把主瓣糊成一个包，峰值 bin 会在 20~23 之间飘。")
    print("        自研通路**本来就不承担双音分辨**（那是 IP 通路 4096 点 + S=/A= 行的活）。")

    # ---------- 5) 量程检查: 加窗后是否仍在 16 位有符号内 ----------
    print("\n" + "=" * 78)
    print("【5】定点量程检查（会不会溢出/标度跑偏）")
    print("=" * 78)
    mx = 0
    for c, w in zip(adc_sine(1000.0, amp=127.0), hann):
        s = c - 128
        mx = max(mx, abs((s * w) >> 7))
    print("  满幅正弦 s∈[-127,127] 时, max|(s*w)>>7| = %d  (16 位有符号上限 32767) -> %s"
          % (mx, "OK ✅" if mx <= 32767 else "溢出 ❌"))
    print("  理论极值: s=-128,w=32768 -> -32768 ; s=+127,w=32768 -> +32512  (都落在 [-32768,32767])")


if __name__ == "__main__":
    main()
