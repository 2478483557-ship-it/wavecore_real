# -*- coding: utf-8 -*-
"""扫频评估: NN 波形识别在**不同频率**下的准确率, 回答"识别频段到底有多宽"。

关键约束(与规则法共用): 特征都是从**一帧 1024 点**里算出来的,
所以一帧里能装多少个周期, 直接决定特征可不可信。
   帧长(时间) = 1024 / fs          fs 由时基抽取决定(默认 T1 = 50kHz)
   帧内周期数 = f / fs * 1024
T1 下帧长 20.48ms; T2(12.5kHz) 下 81.9ms —— 时基是在**用高频换低频**。
"""
import numpy as np
import importlib.util, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('twn', os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py'))
# 不执行训练, 只借它的 feats/gen 定义: 直接读源码里的函数
src = open(os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py'), encoding='utf-8').read()
ns = {}
exec(src[src.index('import numpy'):src.index('Xtr, Ytr = make')], ns)
feats, gen, Q = ns['feats'], ns['gen'], 32767
W1q = np.array([int(l, 16) for l in open(os.path.join(ROOT,'src','nn_w1.hex'))], dtype=int)
W1q = np.where(W1q > 32767, W1q - 65536, W1q).reshape(6, -1)
W2q = np.array([int(l, 16) for l in open(os.path.join(ROOT,'src','nn_w2.hex'))], dtype=int)
W2q = np.where(W2q > 32767, W2q - 65536, W2q).reshape(-1, 4)
b1q = np.array([int(l, 16) for l in open(os.path.join(ROOT,'src','nn_b1.hex'))], dtype=int)
b1q = np.where(b1q > 32767, b1q - 65536, b1q)
b2q = np.array([int(l, 16) for l in open(os.path.join(ROOT,'src','nn_b2.hex'))], dtype=int)
b2q = np.where(b2q > 32767, b2q - 65536, b2q)
import json
meta = json.load(open(os.path.join(ROOT,'src','nn_meta.json'), encoding='utf-8'))
SH1, SH2 = meta['sh1'], meta['sh2']
print('权重: W1%s W2%s  SH1=%d SH2=%d' % (W1q.shape, W2q.shape, SH1, SH2))

def infer1(f):
    xq = np.clip(np.round(f * Q), 0, Q).astype(np.int64)
    hq = np.clip(((xq @ W1q) >> SH1) + b1q, 0, Q)
    oq = ((hq @ W2q) >> SH2) + b2q
    return int(np.argmax(oq))

NAMES = ["正弦", "方波", "三角", "其他"]
FS = 50000.0
N = 1024
rng = np.random.default_rng(7)

def wave(cls, f, duty=0.5):
    n = np.arange(N)
    t = 2 * np.pi * f * n / FS
    if cls == 0:   x = np.sin(t)
    elif cls == 1: x = np.where(((f * n / FS) % 1.0) < duty, 1.0, -1.0)
    elif cls == 2: x = 2 * np.abs(2 * ((f * n / FS) % 1.0) - 1) - 1
    else:          x = 0.6*np.sin(t) + 0.4*np.sin(2.7*t)
    x = x + rng.normal(0, 0.03, N)
    return x / (np.max(np.abs(x)) + 1e-9)

print()
print('帧内周期数 / 各类识别准确率  (fs=50kHz, N=1024)')
print('%-10s %8s  %6s %6s %6s %6s' % ('频率', '周期数', '正弦', '方波', '三角', '其他'))
for f in [100, 200, 300, 500, 1000, 3000, 10000, 20000]:
    acc = []
    for cls in range(4):
        hit = sum(1 for _ in range(60) if infer1(feats(wave(cls, f))) == cls)
        acc.append(100.0 * hit / 60)
    print('%-10s %8.1f  %5.0f%% %5.0f%% %5.0f%% %5.0f%%' % (
        '%d Hz' % f, f / FS * N, acc[0], acc[1], acc[2], acc[3]))
