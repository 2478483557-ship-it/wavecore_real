# -*- coding: utf-8 -*-
"""定点 FFT vs 浮点金标准：量化误差有多大。

为什么要这个：
    论文/答辩里说"自研 FFT 精度够用"，得有数。只说"能用"没有说服力。
    这里用 Python 复现 RTL 的定点行为，和 float64 的 FFT 对比，给出 RMSE。

复现的 RTL 口径（来自 self_fft_1024.v）：
    输入   s = ad_cap ^ 0x80           偏移二进制转补码，范围 [-128, 127]
    加窗   din = (s * w) >> 7          w 是 Q15 窗系数（32768 = 1.0）
    蝶形   每级 >>> 1                   防溢出，共 10 级 -> 总量化 2^-10
    旋转因子 Q15（32768 = 1.0），乘法后 >>15
    输出   L1 模 = |Re| + |Im|

对比指标：
    · 幅度谱的归一化 RMSE（两边都除以自身最大值）
    · 峰值 bin 是否一致
    · 峰值幅度相对误差
    · 主瓣 3dB 宽度是否一致

用法：
    python fixed_vs_float_fft.py
"""
import numpy as np

N = 1024
STAGES = 10
Q15 = 32768


def hann_q15(n=N):
    """RTL 里的 Hann 窗：Q15 定点，round(0.5-0.5*cos(2πk/(N-1))) * 32768。"""
    k = np.arange(n)
    w = 0.5 - 0.5 * np.cos(2 * np.pi * k / (n - 1))
    return np.round(w * Q15).astype(np.int64)


def quantize_input(samples_u8, win):
    """偏移二进制 -> 补码 -> 加窗定点。返回 int64 数组。"""
    s = samples_u8.astype(np.int64) - 128          # ^0x80 等价于 -128（8 位）
    return (s * win) >> 7


def fixed_fft_1024(din):
    """复现 RTL：基2 DIT，每级 >>>1，旋转因子 Q15。"""
    re = din.copy()
    im = np.zeros(N, dtype=np.int64)

    # bit-reverse 排列
    idx = np.arange(N)
    rev = np.zeros(N, dtype=int)
    for i in range(STAGES):
        rev = (rev << 1) | ((idx >> i) & 1)
    re = re[rev]
    im = im[rev]

    # Q15 旋转因子
    tw_re = np.round(np.cos(2 * np.pi * np.arange(N) / N) * (Q15 - 1)).astype(np.int64)
    tw_im = np.round(-np.sin(2 * np.pi * np.arange(N) / N) * (Q15 - 1)).astype(np.int64)

    length = 2
    for _ in range(STAGES):
        half = length // 2
        step = N // length
        for blk in range(0, N, length):
            for j in range(half):
                t1 = blk + j
                t2 = t1 + half
                w = j * step

                wr, wi = int(tw_re[w]), int(tw_im[w])
                br, bi = int(re[t2]), int(im[t2])
                tr = (br * wr - bi * wi) >> 15
                ti = (br * wi + bi * wr) >> 15

                ar, ai = int(re[t1]), int(im[t1])
                re[t1] = (ar + tr) >> 1
                im[t1] = (ai + ti) >> 1
                re[t2] = (ar - tr) >> 1
                im[t2] = (ai - ti) >> 1
        length *= 2

    return re, im


def float_fft_1024(din):
    """浮点金标准：同样的加窗输入，float64 做 FFT。"""
    return np.fft.fft(din.astype(np.float64))


def l1_mag(re, im):
    """RTL 用的 L1 模：|Re| + |Im|。"""
    return np.abs(re) + np.abs(im)


def analyze(name, samples_u8, win):
    din = quantize_input(samples_u8, win)
    fr, fi = fixed_fft_1024(din)
    fx = float_fft_1024(din)
    xr, xi = fx.real, fx.imag

    mag_fix = l1_mag(fr, fi).astype(np.float64)
    mag_flt = np.abs(np.sqrt(xr ** 2 + xi ** 2))

    # 只看正半谱 1..511（RTL 的扫描范围）
    a = mag_fix[1:512]
    b = mag_flt[1:512]
    if a.max() == 0 or b.max() == 0:
        return None

    # 各自归一化后比
    an = a / a.max()
    bn = b / b.max()

    rmse = float(np.sqrt(np.mean((an - bn) ** 2)))
    maxerr = float(np.max(np.abs(an - bn)))

    pk_fix = int(np.argmax(a)) + 1
    pk_flt = int(np.argmax(b)) + 1

    # 峰值幅度相对误差。
    #   注意：RTL 每级 >>>1，10 级累计把幅度缩小 2^10，这是**设计上的标度**，不是误差。
    #   比较绝对幅度前必须先补回这个因子，否则会算出 99.9% 的假误差。
    a_scaled = a * (2 ** STAGES)
    peak_amp_err = float(abs(a_scaled.max() - b.max()) / b.max() * 100)

    return {
        "name": name,
        "rmse": rmse,
        "maxerr": maxerr,
        "pk_fix": pk_fix,
        "pk_flt": pk_flt,
        "pk_ok": pk_fix == pk_flt,
        "peak_amp_err": peak_amp_err,
    }


def synth_sine(n=N, cycles=20.0, amp=100, offset=128):
    """造一个正弦（1024 点内正好 cycles 个周期）。"""
    k = np.arange(n)
    return np.round(offset + amp * np.sin(2 * np.pi * cycles * k / n)).clip(0, 255).astype(np.uint8)


def synth_square(n=N, cycles=20.0, amp=100, offset=128):
    k = np.arange(n)
    s = np.sign(np.sin(2 * np.pi * cycles * k / n))
    return np.round(offset + amp * s).clip(0, 255).astype(np.uint8)


def main():
    win = hann_q15()

    cases = [
        ("正弦 20 周期", synth_sine(cycles=20)),
        ("正弦 61 周期", synth_sine(cycles=61)),
        ("方波 20 周期", synth_square(cycles=20)),
        ("正弦 小幅 20 周期", synth_sine(cycles=20, amp=10)),
    ]

    print("定点 FFT（Q15 + 每级 >>>1 + L1 模） vs 浮点 FFT（float64）")
    print("输入 1024 点，Hann 窗，比较正半谱 bin 1~511")
    print()
    print("  %-18s  RMSE    最大偏差   峰值bin(定点/浮点)  峰幅误差*" % "用例")
    print("  " + "-" * 74)

    results = []
    for name, data in cases:
        r = analyze(name, data, win)
        if not r:
            print("  %-18s  数据无效" % name)
            continue
        results.append(r)
        print("  %-18s  %.5f  %.5f    %3d / %3d %s      %.3f%%"
              % (name, r["rmse"], r["maxerr"], r["pk_fix"], r["pk_flt"],
                 "✓" if r["pk_ok"] else "✗", r["peak_amp_err"]))

    if results:
        avg = np.mean([r["rmse"] for r in results])
        print()
        print("  平均归一化 RMSE = %.5f  (%.3f dB)" % (avg, 20 * np.log10(avg) if avg > 0 else -999))
        print("  峰值 bin 全部一致: %s" % ("是" if all(r["pk_ok"] for r in results) else "否"))
        print("  * 已补偿每级 >>>1 累计的 2^10 标度因子")


if __name__ == "__main__":
    main()
