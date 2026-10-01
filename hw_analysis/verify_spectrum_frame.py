# -*- coding: utf-8 -*-
"""
verify_spectrum_frame.py —— 0x8E 幅度谱帧的逐字节数值金标准（2026-09-30 新增）

为什么写它：
  0x8E 帧的 512 个字节 = 压缩后的 L1 模，本机跑不了 xsim，肉眼更看不出来。
  按 SK-034/038 的方法：用纯 Python **整数级复刻** self_fft_1024 的流水线
  （同窗表 / 同旋转因子表 / 同 >>>1 与 >>16 截断 / 同位反转寻址 / 同 L1 模），
  再复刻 spec_compress 的压缩公式，把 512 字节提前算出来。板上/仿真读数必须与它对齐。

可信性锚点：
  · 与 tb_self_fft 的整数激励（sq20 / sin20）逐字对齐 → 仿真跑出来可直接对比；
  · 整数 bin 的纯音无窗泄漏 → 幅度只由算术决定，模型给的就是"正确答案"。

用法: python verify_spectrum_frame.py
"""
import math
import os

ROOT = r"C:\Users\Lenovo\WorkBuddy\2026-09-02-11-10-14\wavecore"
N = 1024
FS = 50000.0
DF = FS / N


def load_hex(name, signed=False):
    """读 hex 表。signed=True 时按 16 位补码解释（旋转因子表就是这种存法:
    例如 SIN[256] 存的是 0x8001=32769, 实际是 -32767 —— RTL 里
    `reg signed [15:0]` 读进去自动变负数, 模型必须同样处理）。"""
    p = os.path.join(ROOT, "src", name)
    vals = [int(x, 16) for x in open(p, encoding="ascii").read().split()]
    if signed:
        vals = [v - 0x10000 if v & 0x8000 else v for v in vals]
    return vals


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def s32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


HANN = load_hex("hann_1024.hex")             # Q15, 0..32768, 无符号
COS = load_hex("tw_cos.hex", signed=True)    # Q15 补码, 有符号
SIN = load_hex("tw_sin.hex", signed=True)    # Q15 补码, 有符号(表内为 -sin)
assert len(HANN) == N and len(COS) == 1024 and len(SIN) == 1024


def rev10(v):
    r = 0
    for k in range(10):
        if (v >> k) & 1:
            r |= 1 << (9 - k)
    return r


def fft_mag(codes):
    """整数级复刻 self_fft_1024.v：加窗 -> 10 级 DIF 蝶形 -> 位反转寻址取 L1 模。"""
    re = [0] * N
    im = [0] * N
    for i in range(N):
        s = codes[i] - 128
        re[i] = (s * HANN[i]) >> 7          # (s*w)>>7, 算术右移=向下取整
    for stage in range(10):
        half = 512 >> stage
        nblk = 1 << stage
        for blk in range(nblk):
            base = blk * half * 2
            for j in range(half):
                i1 = base + j
                i2 = i1 + half
                ar, ai = re[i1], im[i1]
                br, bi = re[i2], im[i2]
                o1r = (ar + br) >> 1        # >>>1
                o1i = (ai + bi) >> 1
                dr = ar - br
                di = ai - bi
                tw = (j << stage) & 1023
                cr = COS[tw]
                ci = SIN[tw]
                p_rr = s32(dr * cr)
                p_ii = s32(di * ci)
                p_ri = s32(dr * ci)
                p_ir = s32(di * cr)
                o2r = s16(s32(p_rr - p_ii) >> 16)   # 先 32 位回绕, 再 >>16, 再截 16 位
                o2i = s16(s32(p_ri + p_ir) >> 16)
                re[i1] = s16(o1r)
                im[i1] = s16(o1i)
                re[i2] = o2r
                im[i2] = o2i
    mag = [0] * N
    for k in range(N):
        a = rev10(k)
        mag[k] = abs(re[a]) + abs(im[a])        # L1, 与找峰完全同口径
    return mag


def compress(m):
    """逐字复刻 spec_compress.v 的公式。"""
    if m == 0:
        return 0
    b = m.bit_length() - 1
    if b >= 16:
        return 0xFF
    sh = m << (15 - b)
    return ((b << 4) | ((sh >> 11) & 0xF)) & 0xFF


# ---------------- 激励（与 sim/fft_check/gen_tables.py 完全一致） ----------------
MID, AMP, HI, LO = 128, 99, 228, 28


def sq20():
    return [HI if (n * 20) % N < N // 2 else LO for n in range(N)]


def sin20():
    return [MID + int(round(AMP * math.sin(2 * math.pi * 20 * n / N))) for n in range(N)]


def dual(cycles_a, cycles_b):
    return [MID + int(round(AMP / 2 * math.sin(2 * math.pi * cycles_a * n / N)
                           + AMP / 2 * math.sin(2 * math.pi * cycles_b * n / N)))
            for n in range(N)]


def sin_cycles(c):
    return [MID + int(round(AMP * math.sin(2 * math.pi * c * n / N))) for n in range(N)]


def sine_board(freq, amp=127.0):
    """板上 1kHz 正弦的样子（不锁整数 bin）。"""
    return [max(0, min(255, int(round(128.0 + amp * math.sin(2 * math.pi * freq * i / FS)))))
            for i in range(N)]


def square_board(freq):
    return [255 if (freq * i / FS) % 1.0 < 0.5 else 1 for i in range(N)]


def report(name, codes):
    mag = fft_mag(codes)
    y = [compress(m) for m in mag[:512]]
    peak = max(range(512), key=lambda k: mag[k])
    print("-" * 78)
    print("【%s】" % name)
    print("  峰值 bin = %d  (%.1f Hz)   L1 模 = %d  -> 压缩码 y = %d (0x%02X)"
          % (peak, peak * DF, mag[peak], y[peak], y[peak]))
    for kb in (20, 21, 22, 60, 61, 100, 102, 400):
        if kb < 512:
            mark = " <== 峰值" if kb == peak else ""
            print("    bin%-4d  y=%-3d (0x%02X)   mag=%-6d%s"
                  % (kb, y[kb], y[kb], mag[kb], mark))
    return y, mag, peak


def main():
    print("=" * 78)
    print("0x8E 幅度谱帧 逐字节金标准（整数级复刻 self_fft_1024 + spec_compress）")
    print("bin 宽 = %.4f Hz；y = (b<<4)|frac4 对数压缩（~0.38dB/级）" % DF)
    print("=" * 78)

    # ---- 与 tb_self_fft 的 6 个场景一一对应（仿真会把这里当金标准） ----
    yA, mA, pA = report("A_sq20  方波 20 周期(228/28)  [tb 场景A]", sq20())
    yB, mB, pB = report("B_sin20 正弦 20 周期           [tb 场景B]", sin20())
    yC, mC, pC = report("C_dual20_22 双音(相距2bin)     [tb 场景C]", dual(20, 22))
    yD, mD, pD = report("D_dual20_100 双音(相距80bin)   [tb 场景D]", dual(20, 100))
    yE, mE, pE = report("E_sin20p5 非整数 bin 20.5      [tb 场景E]", sin_cycles(20.5))
    yF, mF, pF = report("F_sin400 高 bin(400)           [tb 场景F]", sin_cycles(400))

    # ---- 板上演示信号（1kHz，非整数 bin 20.480） ----
    yG, mG, pG = report("板上 1kHz 正弦(amp=127)", sine_board(1000.0))
    yH, mH, pH = report("板上 1kHz 方波(1/255)", square_board(1000.0))

    print("=" * 78)
    print("【给 tb_self_fft 的断言值（±1 容差）】")
    print("  A_sq20 : peak_bin=%d  y[20]=%d  y[60]=%d  y[100]=%d" % (pA, yA[20], yA[60], yA[100]))
    print("  B_sin20: peak_bin=%d  y[20]=%d" % (pB, yB[20]))
    print("  C_d22  : peak_bin=%d  (<- 期望范围 19~23)" % pC)
    print("  D_d100 : peak_bin=%d  (<- 两音等幅, 看整数模型给谁)" % pD)
    print("  E_s20p5: peak_bin=%d  (<- 期望 19~22)" % pE)
    print("  F_s400 : peak_bin=%d  y[400]=%d" % (pF, yF[400]))
    print()
    print("【板上 1kHz 演示的预期（瀑布图上看）】")
    print("  正弦: 单根竖线, 峰值 bin=%d (%d 码);  1k 落 20.480 -> bin20/21 双高"
          % (pG, yG[pG]))
    print("  方波: 三根线 bin20/61/102, 压缩码差 = %d / %d（理论 9.5dB/14dB -> ~25/~37 码）"
          % (yH[20] - yH[61], yH[20] - yH[102]))
    print()
    print("【帧校验和参考（1kHz 正弦整帧 512 字节）】")
    s = (0x02 + 0x02 + 0x00 + sum(yG)) & 0xFF
    print("  SUM = 0x%02X  (帧尾字节；帧结构 5A A5 02 02 00 + 512B + SUM)" % s)


if __name__ == "__main__":
    main()
