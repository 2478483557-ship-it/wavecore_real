# -*- coding: utf-8 -*-
"""特征重要性：逐个去掉某个特征重新训练，看准确率掉多少。

目的：f2（峭度）需要用 40 位累加器 + 15x15 乘法 + 两次宽除法，
      是 6 个特征里硬件代价最大的。若它对分类贡献很小，去掉就能大幅省资源。
"""
import sys, io, os, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ROOT = 'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore'
src = io.open(os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py'), encoding='utf-8').read()
head = src[:src.index('Xtr, Ytr = make(400)')]
ns = {'__file__': os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py')}
with contextlib.redirect_stdout(io.StringIO()):
    exec(head, ns)

make, CLASS = ns['make'], ns['CLASS_NAMES']
N_FEAT, N_CLS = ns['N_FEAT'], ns['N_CLS']
LABELS = ['f0占空比', 'f1均值', 'f2峭度', 'f3波峰', 'f4斜率', 'f5过零']


def train_sub(Xtr, Ytr, cols, epochs=4000, lr=0.15, hid=16):
    """只用 cols 这些列训练。"""
    rng = np.random.default_rng(2026)
    A = Xtr[:, cols]
    W1 = rng.normal(0, 0.5, (len(cols), hid)); b1 = np.zeros(hid)
    W2 = rng.normal(0, 0.5, (hid, N_CLS)); b2 = np.zeros(N_CLS)
    Yh = np.eye(N_CLS)[Ytr]
    for _ in range(epochs):
        h = np.maximum(A @ W1 + b1, 0)
        o = h @ W2 + b2
        e = np.exp(o - o.max(1, keepdims=True)); p = e / e.sum(1, keepdims=True)
        d = (p - Yh) / len(A)
        W2 -= lr * (h.T @ d); b2 -= lr * d.sum(0)
        dh = (d @ W2.T) * (h > 0)
        W1 -= lr * (A.T @ dh); b1 -= lr * dh.sum(0)
    return W1, b1, W2, b2


def acc_of(cols, Xtr, Ytr, Xte, Yte):
    W1, b1, W2, b2 = train_sub(Xtr, Ytr, cols)
    p = np.argmax(np.maximum(Xte[:, cols] @ W1 + b1, 0) @ W2 + b2, 1)
    per = [np.mean(p[Yte == i] == i) for i in range(N_CLS)]
    return np.mean(p == Yte), per


Xtr, Ytr = make(400); Xte, Yte = make(150)
allc = list(range(N_FEAT))
base, base_per = acc_of(allc, Xtr, Ytr, Xte, Yte)
print('=== 特征重要性（逐个去掉，重训）===')
print('全 6 个特征基准: %.1f%%' % (100 * base))
print('%-10s %-10s %-10s' % ('去掉', '准确率', '跌幅'))
for j in range(N_FEAT):
    cols = [c for c in allc if c != j]
    a, _ = acc_of(cols, Xtr, Ytr, Xte, Yte)
    print('%-10s %-10.1f%% %-10.1f%%' % (LABELS[j], 100 * a, 100 * (base - a)))
