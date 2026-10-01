# -*- coding: utf-8 -*-
"""
check_self_fft_overflow.py
核实 self_fft_1024.v 的频率换算语句是否存在位宽溢出。

待核语句（src/self_fft_1024.v:346）:
    res_freq <= (pk_bin*24'd50000)>>10;

Verilog LRM (IEEE 1364-2005 §5.4.1/§5.4.2) 规则:
  算术运算符 i*j 的结果位宽 = max(L(i), L(j))
  -> pk_bin(10 位) * 24'd50000(24 位) = **24 位结果**
  -> 而 511*50000 = 25,550,000 需要 25 位 —— 溢出

本脚本只做算术核对, 不改任何文件。
"""
M = 1 << 24   # 24 位无符号上限

print("=" * 62)
print("位宽规则复核")
print("=" * 62)
print("pk_bin     : reg [9:0]   -> 10 bit, 取值 1..511 (扫描条件 cur_bin<=511)")
print("24'd50000  : 24 bit")
print("i*j 结果位宽 = max(10,24) = 24 bit   <-- 溢出点在这里")
print()
print("24 位最大值          = %d" % (M - 1))
print("正确需要的最大值     = 511*50000 = %d  (需要 %d 位)" % (511 * 50000, (511 * 50000).bit_length()))
print("溢出起始 bin         = %d  (即 bin >= %d 开始出错)" % ((M - 1) // 50000 + 1, (M - 1) // 50000 + 1))
print("对应频率             = %.1f Hz" % (((M - 1) // 50000 + 1) * 50000 / 1024))
print()

print("=" * 62)
print("逐点对照")
print("=" * 62)
print("%6s %14s %14s %12s" % ("bin", "正确频率(Hz)", "当前代码报出", "偏差"))
bad = []
for b in [20, 100, 200, 300, 335, 336, 350, 400, 450, 500, 511]:
    true_hz = round(b * 50000 / 1024.0)
    got = ((b * 50000) % M) >> 10
    ok = (got == true_hz)
    if not ok:
        bad.append((b, true_hz, got))
    print("%6d %14d %14d %12s  %s" % (b, true_hz, got,
                                      ("%+d" % (got - true_hz)) if not ok else "0",
                                      "OK" if ok else "<<< 错"))
print()
print("出错 bin 区间: %s" % ("336 ~ 511" if bad else "无"))

print()
print("=" * 62)
print("修复方案")
print("=" * 62)
print("把 24 位乘数加宽到 32 位:")
print("    res_freq <= (pk_bin * 32'd50000) >> 10;")
print("  32 位最大值 %d >= %d  OK" % ((1 << 32) - 1, 511 * 50000))
print()
print("复核修复后:")
allok = True
for b in range(1, 512):
    true_hz = round(b * 50000 / 1024.0)
    got = ((b * 50000) % (1 << 32)) >> 10
    if got != true_hz:
        allok = False
        print("  bin %d 仍不符: %d vs %d" % (b, got, true_hz))
print("  全部 %d 个 bin 复核: %s" % (511, "全部一致 OK" if allok else "仍有错"))

print()
print("=" * 62)
print("未来变 fs 时的正确位宽")
print("=" * 62)
print("  f = bin * FS_HZ / N")
print("  bin 最大 4095(12 位), FS_HZ 最大 25e6(25 位)")
print("  -> 乘积最大 = 4095*25000000 = %d (需要 %d 位)" % (4095 * 25000000, (4095 * 25000000).bit_length()))
print("  -> 建议中间量用 **40 位**（不是 24，也不是 32）")
