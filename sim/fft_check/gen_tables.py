# -*- coding: utf-8 -*-
"""
生成三峰判据回归仿真用的 1024 点激励表(8bit 无符号, 中心 128)

为什么用"查表"而不是仿真器里的 $sin:
  XSim 2020.2 对 $sin / real 的支持不稳定(实测全 0), 所以统一改成整数查表。
为什么表里正好是整数个周期:
  1024 点 / k 个周期 -> 谱线正好落在第 k 根 bin, 无泄漏。
  这样"期望值"是纯算术推出来的, 不靠肉眼判断, 仿真结果对不上就是代码有病。

用法: python gen_tables.py
输出: sq20.hex / sin20.hex / dual20_22.hex
"""
import math
import os

N = 1024
HI, LO, MID, AMP = 228, 28, 128, 99


def w(name, vals):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    with open(p, 'w', encoding='ascii') as f:
        f.write('\n'.join('%02X' % (v & 0xFF) for v in vals) + '\n')
    print('%-16s %d 点   min=%d max=%d' % (name, len(vals), min(vals), max(vals)))


# A. 20 周期方波 -> 基波 bin20, 3 次谐波 bin60, 5 次 bin100
#    50% 占空比按"相位"定义(phase<512 为高), 与采样率无关, 一定对称
w('sq20.hex', [HI if (n * 20) % N < N // 2 else LO for n in range(N)])

# B. 20 周期正弦 -> 只有一根谱线(bin20); 旁瓣必须低于"主峰/8"门限
w('sin20.hex',
  [MID + int(round(AMP * math.sin(2 * math.pi * 20 * n / N))) for n in range(N)])

# C. 双音 20 周期 + 22 周期(等价 976.6Hz + 1074.2Hz @fs=50kHz)
#    间距 2 bin < 主瓣宽 4 bin -> 本就分不开, 必须报"单峰"
w('dual20_22.hex',
  [MID + int(round(AMP / 2 * math.sin(2 * math.pi * 20 * n / N)
                   + AMP / 2 * math.sin(2 * math.pi * 22 * n / N)))
   for n in range(N)])

# D. 双音 20 周期 + 100 周期(976.6Hz + 4882.8Hz), 相距 80 bin, 真能分开
#    -> 用来证明"GAP 约束没有把真双峰也一起干掉"
w('dual20_100.hex',
  [MID + int(round(AMP / 2 * math.sin(2 * math.pi * 20 * n / N)
                   + AMP / 2 * math.sin(2 * math.pi * 100 * n / N)))
   for n in range(N)])

print()
print('期望(res_freq = bin*50000/1024):')
print('  sq20       : SF=976(bin20)  S2=2929(bin60)  S3=4882(bin100)  <- 方波 3/5 次谐波')
print('  sin20      : SF=976(bin20)  S2=0            S3=0             <- 单峰, 不许有假峰')
print('  dual20_22  : SF~1002(20/21) S2=0            S3=0             <- 2bin 间距分不开, 报单峰')
print('  dual20_100 : SF=976(bin20)  S2=4882(bin100) S3=0             <- 真双峰能分开')
