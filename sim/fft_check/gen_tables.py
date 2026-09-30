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

# E. [09-30 新增] **非整数个周期**: 20.5 周期 -> 谱线正卡在 bin 20.5 正中间。
#    这是"最坏情形": 矩形窗在离主峰 4 个 bin 处泄漏约 13%, 刚好越过"主峰/8"门限。
#    ⚠️ 原来 4 张表抓不到板上那个假峰的原因: 它们全是"整数个周期", 谱线精确落在整数 bin,
#       而矩形窗在整数 bin 处的泄漏**恰好为 0** -> 假峰在仿真里不可能出现(SK-034)。
#       这张表专门补这个盲区, 把板上的 bug 变成**永久回归项**。
#       把 self_fft_1024 的 USE_HANN 改 1'b0 重跑 -> 本表应报出 S2=1171(bin24), 即板上那个假峰。
w('sin20p5.hex',
  [MID + int(round(AMP * math.sin(2 * math.pi * 20.5 * n / N))) for n in range(N)])

# F. [09-30 深夜新增] **高 bin 溢出回归**: 400 个周期 -> bin400。
#    为什么必须有它: 2026-09-30 发现频率换算 `(pk_bin*24'd50000)>>10` 按 Verilog 位宽规则
#    实际只用 24 位相乘, **pk_bin >= 336 就静默溢出**(读数恰好偏 -16384Hz, 与真值差 16384)。
#    原来 5 张激励表全在 bin20/21/22/60/100, 全都低于 336 -> 这个 bug 一直没被测出来。
#    期望: SF = (400*50000)>>10 = 19531Hz
#    修复前会报 3147Hz  -> 本场景必红, 用来锁死这个 bug。
w('sin400.hex',
  [MID + int(round(AMP * math.sin(2 * math.pi * 400 * n / N))) for n in range(N)])

print()
print('期望(res_freq = bin*50000/1024):')
print('  sq20       : SF=976(bin20)  S2=2929(bin60)  S3=4882(bin100)  <- 方波 3/5 次谐波')
print('  sin20      : SF=976(bin20)  S2=0            S3=0             <- 单峰, 不许有假峰')
print('  dual20_22  : SF~1002(20/21) S2=0            S3=0             <- 2bin 间距分不开, 报单峰')
print('  dual20_100 : {SF,S2} = {976(bin20), 4882(bin100)} 两峰都对, 不保证谁排第一')
print('  sin20p5    : SF~976(bin20/21) S2=0 S3=0   <- 非整数 bin: 不许有假峰')
print("               把 self_fft_1024 的 USE_HANN 改 1'b0 重跑, 这里应变成 S2=1171(bin24) = 负向对照")
print('  sin400     : SF=19531(bin400) S2=0  S3=0   <- **高 bin 溢出回归**:')
print('               修复前会报 3147Hz(偏 -16384Hz); 用来锁死"频率换算位宽溢出"这个 bug')
