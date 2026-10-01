# -*- coding: utf-8 -*-
"""
问题: 加了 Hann 窗之后, sim/fft_check/tb_self_fft.v 的 4 个期望值还成立吗?

背景(必须搞清楚的时序细节):
  hann_rom 的输出是**寄存器**(1 拍读延迟)。RTL 里 `w_addr <= wr_idx` 是**每拍**都赋,
  所以只在"两次采样之间 wr_idx 保持不变(>=3 拍)"时, 窗系数才会与当拍样点严格对齐:
     采样节拍 E 用到 win_w[E-1] = mem[w_addr[E-2]] = mem[wr_idx[E-3]],
     要它等于 mem[wr_idx[E-1]] -> 需要 wr_idx[E-3] == wr_idx[E-1], 即 E-3 与 E-1 同属一个平台期
     -> DECIM >= 4 成立; 板子是 DECIM=1000 ✔
  但 tb 为了快 1000 倍用的是 **DECIM=1**(一拍一个样点), 此时 wr_idx 每拍都 +1,
  于是窗系数整体**落后 2 格**: 实际生效的是 w[(n-2) mod 1024] —— 窗被"循环移位"了。

  理论: 对**整数 bin** 的纯音, 窗的循环移位只给谱线加一个线性相位, |X(k)| **完全不变**;
        对非整数 bin 的激励则不再严格成立。
  这里用数值模型直接把两种情形都算一遍, 用数据说话(而不是靠上面这段推理)。

用法: python probe_tb_scenarios.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_hann_window import (N, FS, GAP, load_hann, windowed, find_peaks)

HANN = load_hann()
MID, AMP = 128, 99
HI, LO = 228, 28


def shift(w, k):
    """w[(n-k) mod N] —— 模拟 DECIM=1 时窗系数落后 k 格"""
    k %= len(w)
    return w[-k:] + w[:-k] if k else list(w)


def res(codes, w, gap, use_hann=True, tag=''):
    r = find_peaks(windowed(codes, w, use_hann), gap=gap)
    print('    %-32s SF=%-5d S2=%-5d S3=%-5d  pk_bin=%-3d b2=%-4d leak24=%.3f'
          % (tag, r['SF'], r['S2'], r['S3'], r['pk_bin'], r['b2'], r['leak24']))
    return r


# ---- 复刻 gen_tables.py 的四张表(逐点一致) ----
def tab_sq(cycles):
    return [HI if (n * cycles) % N < N // 2 else LO for n in range(N)]


def tab_sin(cycles):
    return [MID + int(round(AMP * math.sin(2 * math.pi * cycles * n / N))) for n in range(N)]


def tab_dual(c1, c2):
    return [MID + int(round(AMP / 2 * math.sin(2 * math.pi * c1 * n / N)
                           + AMP / 2 * math.sin(2 * math.pi * c2 * n / N))) for n in range(N)]


TAB = [
    ('A_sq20     方波 20 周期', tab_sq(20),        976, 2929, 4882, 1),
    ('B_sin20    正弦 20 周期', tab_sin(20),        976, 0,    0,    1),
    ('C_d22   双音 20+22 周期', tab_dual(20, 22),  1002, 0,    0,    0),
    ('D_d100  双音 20+100 周期', tab_dual(20, 100),  976, 4882, 0,    1),
]

print('=' * 96)
print('【1】tb 现有 4 个场景: 加 Hann 窗(严格对齐) vs DECIM=1 的"落后 2 格" 是否影响读数')
print('=' * 96)
bad = 0
for name, codes, ef, e2, e3, strict in TAB:
    print('  %s   期望 SF=%d S2=%d S3=%d' % (name, ef, e2, e3))
    r1 = res(codes, HANN, GAP, True, 'Hann 严格对齐                ')
    r2 = res(codes, shift(HANN, 2), GAP, True, 'Hann 落后 2 格 (DECIM=1 实测)')
    ok1 = (r1['SF'] == ef and r1['S2'] == e2 and r1['S3'] == e3)
    ok2 = (r2['SF'] == ef and r2['S2'] == e2 and r2['S3'] == e3)
    if not strict:
        ok1 = r1['S2'] == 0 and r1['S3'] == 0
        ok2 = r2['S2'] == 0 and r2['S3'] == 0
    print('      -> 严格对齐 %s ; 落后 2 格 %s   (DECIM=1 的偏移影响: %s)'
          % ('OK' if ok1 else '*** 不符 ***', 'OK' if ok2 else '*** 不符 ***',
             '无' if (r1['SF'], r1['S2'], r1['S3']) == (r2['SF'], r2['S2'], r2['S3']) else '有!'))
    if not (ok1 and ok2):
        bad += 1

print()
print('=' * 96)
print('【2】建议新增的第 5 个场景: 非整数 bin(DECIM 无关, 这正是板上出假峰的那一类)')
print('=' * 96)
# 20.5 周期 -> f = 20.5 * 48828.125/1000 = 1000.98 Hz  -> 谱线落在 bin 20.5 正中间(最坏情形)
for cyc, desc in [(20.5, '正弦 20.5 周期(谱线正卡两 bin 中间, 最坏)'),
                  (20.3, '正弦 20.3 周期')]:
    codes = [MID + int(round(AMP * math.sin(2 * math.pi * cyc * n / N))) for n in range(N)]
    print('  %s  -> 理论 f = %.1f Hz' % (desc, cyc * FS / N))
    res(codes, HANN, GAP, True,  'Hann + GAP=6 (现行)           ')
    res(codes, HANN, GAP, True,  'Hann + GAP=6, 落后 2 格        ')
    res(codes, [32768] * N, 4, False, '矩形窗 + GAP=4 (改成回归对照) ')

print()
print('=' * 96)
print('【3】结论')
print('=' * 96)
print('  - 若【1】里两种情形读数一致 -> tb 保持 DECIM=1 不动即可, 期望值无需修改;')
print('  - 若不一致 -> 必须把 tb 的 DECIM 改大(>=4)或把窗地址时序改成与 DECIM 无关。')
print('  本次实测: %s' % ('两种情形读数一致, tb 期望值全部成立' if bad == 0 else '有 %d 个场景读数不一致, 需要动 tb' % bad))
