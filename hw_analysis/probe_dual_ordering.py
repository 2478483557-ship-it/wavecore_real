# -*- coding: utf-8 -*-
"""
探针 2: 加 Hann 窗后, tb 场景 C(双音 20+22) 和 D(双音 20+100) 的**峰序**还稳不稳?

现象(probe_tb_scenarios.py):
  - C: 模型报 SF=1074(bin22), 而 tb 期望 1002±60(=1074 超差)
  - D: 模型报 SF=4882(bin100)/S2=976(bin20), 与 tb 期望**峰序相反**
两者都不是"窗把人弄坏了", 而是: 双音里两个音**幅度相等**时, 谁排第一是**并列**的,
并列的胜负由数值噪声(>7 位截断取整)决定 —— 这类测试本身就是"读秒级不稳"的。

这里把 bin20 与 bin100 / bin20 与 bin22 的实际幅度量出来, 看清楚差多少。
然后给两个可选修法各算一遍:
  (甲) 判据放松: D 只要求 {SF,S2} = {976,4882} 且 S3=0 (不管谁第一);
  (乙) 改成"不等幅双音"(大音 60 / 小音 40): 峰序**由设计决定**, 不再靠噪声。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_hann_window import (N, FS, load_hann, fft, windowed)

HANN = load_hann()
MID, AMP = 128, 99


def mags(codes, w, use_hann=True):
    X = fft(windowed(codes, w, use_hann))
    return [abs(X[k].real) + abs(X[k].imag) for k in range(N)]


def show(codes, w, use_hann, tag):
    m = mags(codes, w, use_hann)
    top = sorted(range(1, 512), key=lambda k: -m[k])[:4]
    peak = max(m[1:512])
    print('    %-34s 前 4 大 bin: ' % tag +
          '  '.join('bin%d=%.0f(%.1f%%)' % (k, m[k], 100.0 * m[k] / peak) for k in top))


print('=' * 100)
print('【C】双音 20+22(=976.6 + 1074.2 Hz), 等幅 49.5/49.5')
print('=' * 100)
c22 = [MID + int(round(AMP / 2 * math.sin(2 * math.pi * 20 * n / N)
                       + AMP / 2 * math.sin(2 * math.pi * 22 * n / N))) for n in range(N)]
show(c22, [32768] * N, False, '矩形窗 (09-30 之前)')
show(c22, HANN, True, 'Hann 窗 (现行)')

print()
print('=' * 100)
print('【D】双音 20+100(=976.6 + 4882.8 Hz), 等幅 49.5/49.5')
print('=' * 100)
d100 = [MID + int(round(AMP / 2 * math.sin(2 * math.pi * 20 * n / N)
                        + AMP / 2 * math.sin(2 * math.pi * 100 * n / N))) for n in range(N)]
show(d100, [32768] * N, False, '矩形窗 (09-30 之前)')
show(d100, HANN, True, 'Hann 窗 (现行)')

print()
print('=' * 100)
print('【D-乙】不等幅双音 20+100: 大音 60 / 小音 40  -> 峰序应由设计决定')
print('=' * 100)
d100b = [MID + int(round(60 * math.sin(2 * math.pi * 20 * n / N)
                         + 40 * math.sin(2 * math.pi * 100 * n / N))) for n in range(N)]
print('  幅度范围: min=%d max=%d (必须落在 0..255)' % (min(d100b), max(d100b)))
m = mags(d100b, HANN, True)
pk = max(m[1:512])
for k in (20, 100):
    print('    bin%-4d 幅度=%.0f (%.1f%% of peak)  %s'
          % (k, m[k], 100.0 * m[k] / pk, '<- 主峰' if m[k] == pk else '<- 第二峰'))
show(d100b, HANN, True, 'Hann 窗 + 不等幅')
show(d100b, [32768] * N, False, '矩形窗 + 不等幅(对照)')

print()
print('=' * 100)
print('结论')
print('=' * 100)
print('  C 的两个音只隔 2 bin, 加窗后主瓣糊成一团, bin20/21/22 幅度接近 -> 判据不能要求"刚好 1002±60";')
print('  D 等幅时峰序是并列的, 由取整噪声决定 -> 要么放松成"集合相等", 要么改成不等幅让峰序确定。')
