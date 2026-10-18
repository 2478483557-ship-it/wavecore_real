# -*- coding: utf-8 -*-
"""用**当前权重**重新生成 wave_nn 的测试向量。

向量格式：每行 7 个 4 位 hex = f0..f5（Q15） + 期望类别（用当前定点模型算出）

为什么必须重新生成：SH1/SH2 或权重一改，同样的特征会得到不同判决。
沿用旧向量会出现"RTL 与模型不一致"的假失败（实测 PASS=61 FAIL=3）。
"""
import sys, io, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

ROOT = 'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore'
# 复用训练脚本里已定好的权重与移位
src = io.open(os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py'), encoding='utf-8').read()
head = src[:src.index("pred_f, _ = infer(Xte)")]
# 让训练脚本自己跑出权重（它会现场训练）
ns = {'__file__': os.path.join(ROOT, 'hw_analysis', 'train_wave_nn.py')}
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(head, ns)

Q = ns['Q']; infer = ns['infer']; make = ns['make']; CLASS = ns['CLASS_NAMES']
W1q, W2q = ns['W1q'], ns['W2q']
SH1, SH2 = ns['SH1'], ns['SH2']

# 取一批**独立**于训练/验证/测试的特征（不同随机种子）
np.random.seed(20261018)
X, Y = make(16)          # 每类 16 条 = 64 条，与原向量数量一致
pred, _ = infer(X)
# 按测试台期望的顺序：原文件是逐类排列
lines = []
n_ok = 0
for i in range(len(X)):
    fq = [int(np.clip(round(v * Q), 0, Q)) for v in X[i]]
    lines.append(' '.join('%04X' % v for v in fq) + ' %04X' % int(pred[i]))
    n_ok += int(pred[i] == Y[i])

out = os.path.join(ROOT, 'sim', 'wave_nn_check', 'nn_vectors.hex')
io.open(out, 'w', encoding='ascii', newline='\n').write('\n'.join(lines) + '\n')
print('已生成 %d 条向量（SH1=%d SH2=%d）-> %s' % (len(lines), SH1, SH2, out.split('/')[-1]))
print('  其中模型自评正确 %d 条（%.1f%%）' % (n_ok, 100.0 * n_ok / len(lines)))
