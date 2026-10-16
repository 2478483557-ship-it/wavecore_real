# -*- coding: utf-8 -*-
"""确定"复用同一个 DIF 蝶形做 IFFT"的正确变体(纯数值, 不碰 RTL)。

背景: 现有引擎是 Radix-2 DIF, **自然序输入 -> 位反转存储输出**。
要复用它做 IFFT, 必须搞清楚两件事:
  ① 旋转因子共轭(用 -sin)之后, 蝶形算的是 IDFT 还是 DFT?
  ② 位反转: 频谱在存储里是位反转序, 直接喂进去对不对?
这里把三种变体都跑一遍, 和 numpy 的 ifft 对照, 用数字说话。
"""
import cmath, math

N = 1024
REV = [(int(bin(i)[2:].zfill(10)[::-1], 2)) for i in range(N)]


def rev10(x):
    return int(bin(x)[2:].zfill(10)[::-1], 2)


def butterfly(data, conjugate_twiddle):
    """复刻 RTL 的 10 级 DIF 蝶形(浮点版, 只看结构不看定点)。
       data[i] = (re, im)。conjugate_twiddle=True 时用 e^{+j...}(即 -sin)。"""
    re = [d[0] for d in data]
    im = [d[1] for d in data]
    for stage in range(10):
        half = 512 >> stage
        nblk = 1 << stage
        for blk in range(nblk):
            base = blk * half * 2
            for j in range(half):
                i1, i2 = base + j, base + j + half
                ar, ai, br, bi = re[i1], im[i1], re[i2], im[i2]
                dr, di = ar - br, ai - bi
                tw = (j << stage) & 1023
                ang = -2 * math.pi * tw / N
                cr, ci = math.cos(ang), math.sin(ang)
                if conjugate_twiddle:
                    ci = -ci
                re[i1], im[i1] = (ar + br) / 2, (ai + bi) / 2
                re[i2] = (dr * cr - di * ci) / 2
                im[i2] = (dr * ci + di * cr) / 2
    # 引擎把结果按 addr 存, addr = 位反转序列; 取"存储序"读出来
    return [(re[REV[k]], im[REV[k]]) for k in range(N)]


# ---- 造一个频谱: 用真实信号做 FFT 得到 ----
n = range(N)
x = [math.cos(2 * math.pi * 20 * k / N) + 0.5 * math.cos(2 * math.pi * 61 * k / N) for k in n]
X = [sum(x[k] * cmath.exp(-2j * math.pi * i * k / N) for k in n) for i in n]

print('参照: numpy 式 ifft(X) 前 3 点 =',
      ['%.3f%+.3fj' % (v.real, v.imag) for v in [sum(X[k]*cmath.exp(2j*math.pi*i*k/N) for k in n)/N for i in range(3)]])

# 变体 A: 频谱按**存储序**(位反转)喂入, 旋转因子取共轭
Xstore = [(X[rev10(k)].real, X[rev10(k)].imag) for k in range(N)]          # 存储序: 第 k 格存的是 bin rev10(k)
A = butterfly(Xstore, conjugate_twiddle=True)
print('变体A(位反转序输入 + 共轭twiddle) 前3点 =',
      ['%.3f%+.3fj' % (v[0], v[1]) for v in A[:3]])

# 变体 B: 频谱按自然序喂入, 共轭 twiddle
B = butterfly([(v.real, v.imag) for v in X], conjugate_twiddle=True)
print('变体B(自然序输入   + 共轭twiddle) 前3点 =',
      ['%.3f%+.3fj' % (v[0], v[1]) for v in B[:3]])

# 变体 C: 自然序输入, 不共轭
C = butterfly([(v.real, v.imag) for v in X], conjugate_twiddle=False)
print('变体C(自然序输入   + 原 twiddle) 前3点 =',
      ['%.3f%+.3fj' % (v[0], v[1]) for v in C[:3]])
