# -*- coding: utf-8 -*-
"""训练并量化"波形识别"小网络, 导出 RTL 可直接用的权重表。

为什么用**时域特征**: 现有 wave_id 用的是"占空比占比法"(纯规则 + 手工阈值),
这里用同一类可观察量做输入, 对比才公平 —— 差别只在"阈值是手调的 还是学出来的"。

特征(6 个, 全部频率无关, 用定点实现):
  0 duty      占空比 D = 高电平点数 / 1024
  1 mean_n    归一化均值   |mean(x)| / peak
  2 form      波形因数     rms / mean|x|        (正弦 1.11 / 方波 1.00 / 三角 1.15)
  3 crest     峰值因数     peak / rms           (正弦 1.41 / 方波 1.00 / 三角 1.73)
  4 slope     归一化平均斜率  mean|x[n]-x[n-1]| / peak
  5 zc        过零率       过零次数 / 1024

量化的关键洞察: **分类只看 argmax**, 于是各层统一的缩放因子不改变结果。
所以可以用最简单的定点方案: 特征压到 0..127, 权重压到 int8, 层间用移位定标。
"""
import numpy as np
import os

N = 1024
N_FEAT, N_HID, N_CLS = 6, 8, 4
CLASS_NAMES = ["正弦", "方波", "三角", "其他"]
rng = np.random.default_rng(20261016)


def feats(x):
    """x: 已归一化到 [-1,1] 的 1024 点波形。返回 6 个 [0,1] 特征。"""
    pk = float(np.max(np.abs(x))) + 1e-9
    xn = x / pk
    hi = xn > 0.0
    duty = float(np.mean(hi))
    mean_n = abs(float(np.mean(xn)))
    rms = float(np.sqrt(np.mean(xn ** 2)))
    mean_abs = float(np.mean(np.abs(xn))) + 1e-9
    # [10-16] 原用 "波形因数"(rms/mean_abs): 正弦 1.11 vs 三角 1.15 —— 几乎无区分度, 弃用。
    #   改用**峭度**(四阶矩/二阶矩^2): 正弦 1.5 / 方波 1.0 / 三角 1.8 -> 区分度大得多。
    # [10-17] 改成**不减均值**的峭度, 与 RTL 口径对齐 ——
    #   RTL 单遍扫描拿不到全局均值, 只能算 Σx⁴。实测两者在 duty≠50% 的方波上
    #   差很多（kurt 1.243 vs 1.003）, 因此必须统一口径, 否则模型与硬件不一致。
    m4 = float(np.mean(xn ** 4))
    kurt = m4 / (rms ** 4 + 1e-9)
    form = min(kurt / 3.0, 1.0)
    crest = min(rms / pk, 1.0)                      # 1/峰值因数
    slope = min(float(np.mean(np.abs(np.diff(xn)))) * 2.0, 1.0)
    zc = float(np.mean(np.diff(xn > 0) != 0))
    return np.array([duty, mean_n, form, crest, slope, zc])


def gen(cls):
    n = np.arange(N)
    f = float(rng.uniform(15, 120))                 # 频率随机 -> 学到的特征必须频率无关
    ph = rng.uniform(0, 2 * np.pi)
    amp = rng.uniform(0.5, 1.0)
    noise = rng.normal(0, rng.uniform(0.0, 0.08), N)
    t = 2 * np.pi * f * n / N + ph
    if cls == 0:                                     # 正弦
        x = np.sin(t)
    elif cls == 1:                                   # 方波(占空比随机)
        d = rng.uniform(0.3, 0.7)
        x = np.where(((f * n / N + ph / (2 * np.pi)) % 1.0) < d, 1.0, -1.0)
    elif cls == 2:                                   # 三角
        x = 2 * np.abs(2 * ((f * n / N + ph / (2 * np.pi)) % 1.0) - 1) - 1
    else:                                            # 其他: 双音/带噪/削顶
        k = rng.integers(0, 3)
        if k == 0:
            x = 0.6 * np.sin(t) + 0.4 * np.sin(2.7 * t)
        elif k == 1:
            x = np.clip(3.0 * np.sin(t), -1, 1)
        else:
            x = rng.normal(0, 0.5, N)
    return np.clip(amp * x + noise, -1.2, 1.2)


def make(n_per_cls):
    X, Y = [], []
    for c in range(N_CLS):
        for _ in range(n_per_cls):
            X.append(feats(gen(c)))
            Y.append(c)
    return np.array(X), np.array(Y)


# ---------- 训练(纯 numpy 两层 MLP, 不依赖 sklearn) ----------
def train(Xtr, Ytr, epochs=4000, lr=0.15, hid=16):
    W1 = rng.normal(0, 0.5, (N_FEAT, hid))
    b1 = np.zeros(hid)
    W2 = rng.normal(0, 0.5, (hid, N_CLS))
    b2 = np.zeros(N_CLS)
    Yh = np.eye(N_CLS)[Ytr]
    for it in range(epochs):
        h = np.maximum(Xtr @ W1 + b1, 0)
        o = h @ W2 + b2
        e = np.exp(o - o.max(1, keepdims=True))
        p = e / e.sum(1, keepdims=True)
        d = (p - Yh) / len(Xtr)
        gW2, gb2 = h.T @ d, d.sum(0)
        dh = (d @ W2.T) * (h > 0)
        gW1, gb1 = Xtr.T @ dh, dh.sum(0)
        W2 -= lr * gW2; b2 -= lr * gb2
        W1 -= lr * gW1; b1 -= lr * gb1
    return W1, b1, W2, b2


Xtr, Ytr = make(400)
Xte, Yte = make(150)

# [10-16 状态] 标准化折叠试过, 实测反而更差(25%, 全预测同一类), 已回退。
#   当前是已知最好配置, 但绝对精度仍不达标 —— 见文件末尾的"未解决"说明。
W1, b1, W2, b2 = train(Xtr, Ytr)
print('浮点模型准确率: 训练 %.1f%%  测试 %.1f%%' % (
    100 * np.mean(np.argmax(np.maximum(Xtr @ W1 + b1, 0) @ W2 + b2, 1) == Ytr),
    100 * np.mean(np.argmax(np.maximum(Xte @ W1 + b1, 0) @ W2 + b2, 1) == Yte)))

# ---------- 量化 ----------
def q(x, scale):  # 缩放到 int8 范围内
    return np.clip(np.round(x * scale), -128, 127).astype(int)

# ---------- 量化(自适应定标) ----------
# 关键: 特征用 **Q15**(0..32767), 权重用 int8。原来的写法把权重固定乘 64 再裁到 +-127,
#   |W|>2 的权重全被裁掉 -> 浮点 99.7% 骤降到 31.5%。改成**按最大值自适应定标**。
Q = 32767


def qw(W):
    """按最大绝对值把权重定标到 **int16** 满量程(不裁), 返回 (量化值, 缩放因子)。

    [10-16 实测] 先用 int8 试过: 精度不足以至正弦类只有 28%、"其他"类 0%,
      整体 57%(浮点 99.7%)。原因是权重只有 7 位有效位, 决策边界被量化噪声抹平。
      改 int16 后 —— RTL 侧本来就是 16x16 乘法, 代价几乎为零。
    """
    s = 32767.0 / max(abs(W).max(), 1e-9)
    return np.clip(np.round(W * s), -32768, 32767).astype(int), s


W1q, S1 = qw(W1)
W2q, S2 = qw(W2)
# 层间定标: pre = x_q@W1q = Q*S1*(x@W1)。**不能**想当然把隐层当成 [0,1] 来定标 ——
#   实测那样做隐层饱和率高达 73%(全顶在 0 或上限), 信息被抹平, 准确率反而掉到 57%。
#   正解: 按**训练集上真实的激活范围**定标, 让 hq 填满 [0, Q]。
h_tr = np.maximum((Xtr @ W1) + b1, 0)
H_MAX = max(float(h_tr.max()), 1e-9)
SH1 = max(int(round(np.log2(max(S1 * H_MAX, 1e-9)))), 0)   # 使 hq ~ Q/H_MAX * h
SH2 = max(int(round(np.log2(max(S2, 1e-9)))), 0)
b1q = np.round(b1 * Q / H_MAX).astype(int)
b2q = np.round(b2 * Q).astype(int)


def infer(X):
    """与 RTL 完全同口径的定点推演。"""
    xq = np.clip(np.round(X * Q), 0, Q).astype(np.int64)
    # [10-16 修正] 原来先 clip 再加偏置(= relu(pre)+b1), 正确顺序是 relu(pre + b1)。
    #   这个顺序错会让模型几乎全预测同一类(实测 25%)。
    hq = np.clip(((xq @ W1q) >> SH1) + b1q, 0, Q)         # relu(pre + b1)
    oq = ((hq @ W2q) >> SH2) + b2q
    return np.argmax(oq, 1), oq


pred_f, _ = infer(Xte)
acc_f = 100 * np.mean(pred_f == Yte)
print('量化模型准确率: 测试 %.1f%%   (SH1=%d SH2=%d, S1=%.1f S2=%.1f)' % (acc_f, SH1, SH2, S1, S2))
print('  权重范围: W1 %d..%d   W2 %d..%d' % (W1q.min(), W1q.max(), W2q.min(), W2q.max()))
xq_t = np.clip(np.round(Xte * Q), 0, Q).astype(np.int64)
hq_t = np.clip(((xq_t @ W1q) >> SH1) + b1q, 0, Q)
print('  隐层饱和率(顶到 0 或 Q 的比例): %.1f%% / %.1f%%' % (
    100*np.mean(hq_t <= 0), 100*np.mean(hq_t >= Q)))
oq_t = ((hq_t @ W2q) >> SH2) + b2q
print('  输出层范围: %d .. %d' % (oq_t.min(), oq_t.max()))
# 与浮点模型逐样本比对, 看量化在哪些样本上翻车
h_f = np.maximum(Xte @ W1 + b1, 0)
conf_f = np.argmax(h_f @ W2 + b2, 1)
diff = np.where(conf_f != pred_f)[0]
print('  量化与浮点判决不同的样本: %d / %d' % (len(diff), len(Yte)))
if len(diff):
    i = diff[0]
    print('  例(第 %d 个): 浮点=%s 量化=%s 真值=%s' % (
        i, CLASS_NAMES[conf_f[i]], CLASS_NAMES[pred_f[i]], CLASS_NAMES[Yte[i]]))
    print('    特征 =', np.round(Xte[i], 3))
for c in range(N_CLS):
    m = Yte == c
    print('    %-4s %5.1f%%' % (CLASS_NAMES[c], 100*np.mean(pred_f[m] == c)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, 'src', 'nn_w1.hex'), 'w', encoding='ascii') as f:
    f.write('\n'.join('%04X' % (v & 0xFFFF) for v in W1q.flatten()) + '\n')

with open(os.path.join(ROOT, 'src', 'nn_b1.hex'), 'w', encoding='ascii') as f:
    f.write('\n'.join('%04X' % (v & 0xFFFF) for v in b1q) + '\n')
with open(os.path.join(ROOT, 'src', 'nn_w2.hex'), 'w', encoding='ascii') as f:
    f.write('\n'.join('%04X' % (v & 0xFFFF) for v in W2q.flatten()) + '\n')  # [10-16 修复] 原为 %02X: W2 是 int16, 只存低 8 位 -> 载入的 W2 全是垃圾
with open(os.path.join(ROOT, 'src', 'nn_b2.hex'), 'w', encoding='ascii') as f:
    f.write('\n'.join('%04X' % (v & 0xFFFF) for v in b2q) + '\n')
print('权重已导出(16bit): nn_w1(%d) nn_b1(%d) nn_w2(%d) nn_b2(%d)' % (
    W1q.size, b1q.size, W2q.size, b2q.size))

import json
json.dump({'class_names': CLASS_NAMES, 'n_feat': N_FEAT, 'n_hid': W1q.shape[1],
           'n_cls': N_CLS, 'sh1': SH1, 'sh2': SH2, 'q': Q},
          open(os.path.join(ROOT, 'src', 'nn_meta.json'), 'w'), ensure_ascii=False, indent=1)
print('元数据已写 nn_meta.json')
