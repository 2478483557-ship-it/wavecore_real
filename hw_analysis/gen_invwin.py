# -*- coding: utf-8 -*-
"""生成逆窗表 invwin_1024.hex（Q12 定点）—— 基于**实际的** hann_1024.hex。

为什么需要它：
  频谱是在"加了 Hann 窗"的数据上算的。对加窗后的频谱做反变换，
  得到的时域 = 原信号 × 窗函数 —— 两端幅度掉到 0，波形是纺锤形。
  回放时把每个点除以窗值（用查表 + 乘法代替除法），波形就恢复等幅。

门限取 0.25：
  Hann 在两端趋近 0，直接除会放大成爆炸。门限以下按 1/0.25 = 4 倍增益封顶。
  代价是两端各约 171 点（17%）是"封顶补偿"，幅度仍略低，但不影响观察。

关键：逆表必须用 hann_1024.hex 的**真实数值**算，不能重新推导公式，
      否则两表的相位/周期约定不一致（实测本工程用 2*pi*n/1024）。
"""
import numpy as np
import io

SRC = 'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore/src/hann_1024.hex'
OUT = 'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore/src/invwin_1024.hex'

h = np.array([int(l, 16) for l in io.open(SRC) if l.strip()], dtype=float)
assert len(h) == 1024, '窗表点数不对: %d' % len(h)

LIM = 0.25                        # 增益门限（对应窗值 1/4）
Q = 12                            # 定点小数位

wn = h / 32768.0                  # 归一化
eff = np.maximum(wn, LIM)         # 限幅
inv = 1.0 / eff
val = np.round(inv * (1 << Q)).astype(int)

print('逆窗表 invwin_1024.hex (Q12)，基于实际 hann_1024.hex')
print('  窗值范围      : %.4f ~ %.4f' % (wn.min(), wn.max()))
print('  补偿增益      : %.2f ~ %.2f 倍 -> 定点 %d ~ %d'
      % (inv.min(), inv.max(), val.min(), val.max()))
assert val.max() < 65536, '16 位溢出'
print('  16 位上限 65535 ：OK')
covered = int((wn >= LIM).sum())
print('  门限以上(真补偿): %d 点 (%.0f%%)，两端各封顶约 %d 点'
      % (covered, 100.0 * covered / 1024, (1024 - covered) // 2))

io.open(OUT, 'w', encoding='ascii', newline='\n').write(
    '\n'.join('%04X' % v for v in val) + '\n')
print('  已写 invwin_1024.hex (%d 点)' % len(val))
