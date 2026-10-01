# -*- coding: utf-8 -*-
"""
verify_freq_conv_fix2.py  (修正版)

上一版脚本的基准取错了：IP 通路 `+2048 >>12` 是**四舍五入**，
而我拿"直接截断"当正确值去比 —— 于是凭空多出 2048 处"错"（正好是舍入差异）。

本版：
  · IP  通路基准 = (bin*50000 + 2048) >> 12       （四舍五入，与 RTL 一致）
  · 自研通路基准 = (bin*50000) >> 10               （截断，与 RTL 一致）
"""
M = lambda b: (1 << b) - 1


def sim(bin_, mult_bits, out_bits, shift, addend=0, add_bits=32):
    """按 Verilog 上下文位宽规则模拟"""
    W = max(out_bits, mult_bits, add_bits, 10)
    prod = (bin_ * 50000) & M(W)
    val = (prod + addend) & M(W)
    return (val >> shift) & M(out_bits)


def true_ip(b):      # N=4096, 四舍五入
    return (b * 50000 + 2048) >> 12


def true_self(b):    # N=1024, 截断
    return (b * 50000) >> 10


print("=" * 72)
print("① IP 通路 fft_demo.v   (N=4096, +2048 四舍五入)")
print("=" * 72)
print("%6s %10s %14s %14s" % ("bin", "正确Hz", "修复前", "修复后"))
for b in [82, 246, 336, 400, 819, 1000, 2048, 4095]:
    t = true_ip(b)
    old = sim(b, 16, 24, 12, 2048, 12)
    new = sim(b, 32, 24, 12, 2048, 32)
    print("%6d %10d %14d %14d   %s" % (b, t, old, new,
          ("旧OK" if old == t else "旧错") + "/" + ("新OK" if new == t else "新错")))
n_old = sum(1 for b in range(1, 4096) if sim(b, 16, 24, 12, 2048, 12) != true_ip(b))
n_new = sum(1 for b in range(1, 4096) if sim(b, 32, 24, 12, 2048, 32) != true_ip(b))
print()
print("  全 bin 扫描 (1..4095):")
print("    修复前: %4d 个 bin 错   (首个错 bin=336 -> %.0f Hz)" % (n_old, 336 * 50000 / 4096))
print("    修复后: %4d 个 bin 错" % n_new)
assert n_new == 0, "IP 通路修复后仍有错!"
print("    => 修复后 **0 错** ✅")

print()
print("=" * 72)
print("② 自研通路 self_fft_1024.v   (N=1024, 截断)")
print("=" * 72)
print("%6s %10s %14s %14s" % ("bin", "正确Hz", "修复前", "修复后"))
for b in [20, 61, 102, 335, 336, 400, 500, 511]:
    t = true_self(b)
    old = sim(b, 24, 24, 10, 0, 24)
    new = sim(b, 32, 24, 10, 0, 32)
    print("%6d %10d %14d %14d   %s" % (b, t, old, new,
          ("旧OK" if old == t else "旧错") + "/" + ("新OK" if new == t else "新错")))
n_old = sum(1 for b in range(1, 512) if sim(b, 24, 24, 10, 0, 24) != true_self(b))
n_new = sum(1 for b in range(1, 512) if sim(b, 32, 24, 10, 0, 32) != true_self(b))
print()
print("  全 bin 扫描 (1..511):")
print("    修复前: %4d 个 bin 错   (首个错 bin=336 -> %.0f Hz)" % (n_old, 336 * 50000 / 1024))
print("    修复后: %4d 个 bin 错" % n_new)
assert n_new == 0, "自研通路修复后仍有错!"
print("    => 修复后 **0 错** ✅")

print()
print("=" * 72)
print("③ 与板上实测对照（验证位宽模型本身是对的）")
print("=" * 72)
c1 = sim(82, 16, 24, 12, 2048, 12)
c2 = sim(20, 24, 24, 10, 0, 24)
print("  板测 IP  : 1kHz -> S=0001001 ; 模型(24位) = %d  %s" % (c1, "✅吻合" if c1 == 1001 else "❌"))
print("  板测 自研: 1kHz -> SF=0000976 ; 模型(24位) = %d  %s" % (c2, "✅吻合" if c2 == 976 else "❌"))
print()
print("  ★ 两条通路都在 24 位下与实测逐字吻合 -> '24 位溢出' 这个诊断成立。")
print("  ★ 关键副作用提醒: 自研通路 1kHz 看似正常(bin20 远低于阈值),")
print("    但 **IP 通路阈值只有 bin336 = 4101Hz** —— 即 4.1kHz 以上的信号")
print("    在修复前**全都读错**, 而这一点从未被任何一次上板测试覆盖到。")
