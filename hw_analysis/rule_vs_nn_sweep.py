# -*- coding: utf-8 -*-
"""把 src/wave_id.v 的"占比法"逐行复刻成 Python, 与 NN 在同一批激励上对比。

规则(摘自 wave_id.v v1.1, 作者 2026-09-20):
  50kHz 降采样(每 1000 拍取 1 点); 两阶段各 2048 点:
    阶段0 跟踪 min/max -> mid=(mn+mx)>>1, span=mx-mn
    阶段1 统计 |med-mid| > 3/8*span 的点数 hi_cnt (med 为 3 点中值)
  判决: span<16 -> 其他;  hi_cnt>1720 -> 方波;
        819..1270 -> 正弦;  369..778 -> 三角;  其余 -> 其他
注意: 它总共观察 4096 个降采样点 ≈ **81.9 ms**, 是 NN(1024 点 ≈ 20.5 ms)的 4 倍。
"""
import numpy as np, os, json, sys

R = os.getcwd()
FS, N_ADC = 50000.0, 4096


def ty_rule(x8):
    """x8: uint8 数组(0..255, 中点 128), 长度 >= 4096。返回 0方波/1正弦/2三角/3其他"""
    s = x8.astype(np.int32)
    med = np.array([np.median(s[i - 2:i + 1]) for i in range(2, len(s))], dtype=np.int32)  # 3点中值(流水一节)
    p0 = s[:2048]                                   # 阶段0 看原始降采样点
    mn, mx = int(p0.min()), int(p0.max())
    mid, span = (mn + mx) >> 1, mx - mn
    if span < 16:
        return 3
    th3 = (span >> 2) + (span >> 3)
    seg = med[2048:2048 + 2048]                     # 阶段1 看中值序列
    hi_cnt = int(np.count_nonzero(np.abs(seg - mid) > th3))
    # [10-16] 注意顺序映射: 规则法原生 0=方波/1=正弦/2=三角, 这里统一到 NN 的顺序
    #   0=正弦/1=方波/2=三角/3=其他 —— 之前就是漏了这步映射, 导致对比结果全错。
    if hi_cnt > 1720:            return 1      # 方波
    if 819 <= hi_cnt <= 1270:    return 0      # 正弦
    if 369 <= hi_cnt <= 778:     return 2      # 三角
    return 3


def wave8(cls, f, duty=0.5, noise=0.03, seed=0):
    """造 8bit ADC 样点(中点 128), 与硬件采集口径一致。"""
    rng = np.random.default_rng(seed)
    n = np.arange(N_ADC)
    ph = (f * n / FS) % 1.0
    # 类别顺序与 NN 训练脚本一致: 0=正弦 1=方波 2=三角 3=其他
    if cls == 0:   w = np.sin(2 * np.pi * ph)
    elif cls == 1: w = np.where(ph < duty, 1.0, -1.0)
    elif cls == 2: w = 2 * np.abs(2 * ph - 1) - 1
    else:          w = 0.6 * np.sin(2 * np.pi * ph) + 0.4 * np.sin(2 * np.pi * 2.7 * ph)
    w = w / (np.max(np.abs(w)) + 1e-9)
    w = w + rng.normal(0, noise, N_ADC)
    return np.clip(np.round(128 + 100 * w), 0, 255).astype(np.uint8)


names = ["正弦", "方波", "三角", "其他"]
# NN 侧的定点推理(与 nn_freq_sweep 同口径)
def load16(nm):
    v = np.array([int(l, 16) for l in open(os.path.join(R, 'src', nm))], dtype=np.int64)
    return np.where(v > 32767, v - 65536, v)
W1q = load16('nn_w1.hex').reshape(6, -1); W2q = load16('nn_w2.hex').reshape(-1, 4)
b1q, b2q = load16('nn_b1.hex'), load16('nn_b2.hex')
meta = json.load(open(os.path.join(R, 'src', 'nn_meta.json'), encoding='utf-8'))
SH1, SH2, Q = meta['sh1'], meta['sh2'], 32767
src = open(os.path.join(R, 'hw_analysis', 'train_wave_nn.py'), encoding='utf-8').read()
ns = {}
exec(src[src.index('import numpy'):src.index('Xtr, Ytr = make')], ns)
feats = ns['feats']


def nn_predict(x8):
    v = (x8.astype(np.float64) - 128.0) / 100.0       # 回到 ±1
    f = feats(v[:1024])                               # NN 用 1024 点
    xq = np.clip(np.round(f * Q), 0, Q).astype(np.int64)
    hq = np.clip(((xq @ W1q) >> SH1) + b1q, 0, Q)
    return int(np.argmax(((hq @ W2q) >> SH2) + b2q))


print('频率      |  占比法 TY (82ms 窗口)        |  NN (20ms 窗口)')
print('          |  正弦  方波  三角  其他       |  正弦  方波  三角  其他')
print('-' * 76)
for f in [50, 100, 200, 300, 500, 1000, 3000, 10000, 20000]:
    r_acc, n_acc = [], []
    for cls in range(4):
        rth = sum(1 for k in range(40) if ty_rule(wave8(cls, f, seed=k)) == cls)
        nth = sum(1 for k in range(40) if nn_predict(wave8(cls, f, seed=k)) == cls)
        r_acc.append(100.0 * rth / 40); n_acc.append(100.0 * nth / 40)
    print('%-9s | %4.0f%% %4.0f%% %4.0f%% %4.0f%%  | %4.0f%% %4.0f%% %4.0f%% %4.0f%%' % (
        '%d Hz' % f, r_acc[0], r_acc[1], r_acc[2], r_acc[3],
        n_acc[0], n_acc[1], n_acc[2], n_acc[3]))
