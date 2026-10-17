# -*- coding: utf-8 -*-
"""为 wave_feat 生成测试向量: 每类波形取 1024 个 8bit 样点 + 期望的 6 个特征。

金标准 = 直接用 train_wave_nn.py 里的 feats() 算(浮点), 再量化为 Q15。
RTL 的结果允许 ±2 LSB 的差异(定点量化 vs 浮点)。
"""
import io
import os
import numpy as np

SRC = 'src/train_tmp.py'
ROOT = 'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore'
FEAT_PY = os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py')

# 取 feats() 的定义
src = io.open(FEAT_PY, encoding='utf-8').read()
ns = {}
exec(src[src.index('import numpy'):src.index('Xtr, Ytr = make')], ns)
feats = ns['feats']

FS, N = 50000.0, 1024


def wave8(cls, seed=0):
    """造 1024 个 8bit ADC 样点(补码, 中点 0)。"""
    rng = np.random.default_rng(seed)
    f = rng.uniform(15, 120)          # 帧内 15~120 个周期, 与训练一致
    ph = rng.uniform(0, 2 * np.pi)
    n = np.arange(N)
    t = 2 * np.pi * f * n / N + ph
    if cls == 0:
        x = np.sin(t)
    elif cls == 1:
        d = rng.uniform(0.3, 0.7)
        x = np.where(((f * n / N + ph / (2 * np.pi)) % 1.0) < d, 1.0, -1.0)
    elif cls == 2:
        x = 2 * np.abs(2 * ((f * n / N + ph / (2 * np.pi)) % 1.0) - 1) - 1
    else:
        k = rng.integers(0, 3)
        if k == 0:
            x = 0.6 * np.sin(t) + 0.4 * np.sin(2.7 * t)
        elif k == 1:
            x = np.clip(3.0 * np.sin(t), -1, 1)
        else:
            x = rng.normal(0, 0.5, N)
    amp = rng.uniform(0.5, 1.0)
    x = np.clip(amp * x + rng.normal(0, 0.03, N), -1.2, 1.2)
    # 归一化到满量程, 转 8bit 补码(±127)
    x = x / (np.max(np.abs(x)) + 1e-9)
    return np.clip(np.round(x * 120), -128, 127).astype(int)


def feat_q15(x8):
    """与 RTL 同口径的 6 个特征。

    ★ 注意口径（这里踩过一次）：xn 已经除以 pk 归一化过了，
      f1/f3 里**不能再除一次 pk** —— 原来的写法多除了一次，
      算出的期望值只有真值的 1/120，导致测试台"全红"却以为是 RTL 错。
      RTL 侧是"x 域累加、最后统一除 pk"，数学上与这里等价：
        f1: |Σv|*32/pk        ==  |mean(v/pk)| * 32768
        f3: √(Σv²)*1024/pk    ==  sqrt(mean((v/pk)²)) * 32768
      过零率用 /1024（不是 /1023）：diff 长度为 1023，但 RTL 按 1024 归一，两端口径对齐。
    """
    v = x8.astype(float)
    pk = np.max(np.abs(v))
    xn = v / pk                        # 归一化到 ±1
    hi = xn > 0
    duty = np.mean(hi)                 # f0 占空比
    mean_n = abs(np.mean(xn))          # f1 归一化均值（xn 已归一化）
    rms = np.sqrt(np.mean(xn ** 2))
    # [10-17] 与 RTL 对齐: 不减均值（RTL 单遍扫描拿不到全局均值）
    m4 = np.mean(xn ** 4)
    kurt = m4 / (rms ** 4 + 1e-9)      # 无量纲
    form = min(kurt / 3.0, 1.0)        # f2 峭度/3
    crest = min(rms, 1.0)              # f3 波峰因数（xn 峰值=1）
    slope = min(np.mean(np.abs(np.diff(xn))) * 2.0, 1.0)   # f4
    zc = np.count_nonzero(np.diff(hi)) / 1024.0            # f5 过零率(/1024)
    f = np.array([duty, mean_n, form, crest, slope, zc])
    return np.clip(np.round(f * 32767), 0, 32767).astype(int)


# ---- 生成 ----
lines = []
summary = []
for cls, name in enumerate(['正弦', '方波', '三角', '其他']):
    for k in range(4):
        x8 = wave8(cls, seed=1000 + cls * 10 + k)
        fq = feat_q15(x8)
        # 一行 = 1024 个样点(2位hex, 补码转无符号存) + 6 个期望特征(4位hex)
        samples = ' '.join('%02X' % (int(v) & 0xFF) for v in x8)
        exps = ' '.join('%04X' % int(v) for v in fq)
        lines.append(samples + ' | ' + exps)
        summary.append((name, k, fq))

out = os.path.join(ROOT, 'sim', 'wave_feat_check', 'feat_vectors.txt')
os.makedirs(os.path.dirname(out), exist_ok=True)
io.open(out, 'w', encoding='ascii', newline='\n').write('\n'.join(lines) + '\n')

print('已生成 %d 条测试向量 -> %s' % (len(lines), out.split('/')[-1]))
print()
print('期望特征(Q15):')
print('%-6s %-3s %-7s %-7s %-7s %-7s %-7s %-7s'
      % ('类', '#', 'f0占空', 'f1均值', 'f2峭度', 'f3波峰', 'f4斜率', 'f5过零'))
for name, k, fq in summary:
    print('%-6s %-3d %-7d %-7d %-7d %-7d %-7d %-7d'
          % (name, k, fq[0], fq[1], fq[2], fq[3], fq[4], fq[5]))
