# -*- coding: utf-8 -*-
"""
probe_interp.py —— 自研 FFT「峰频率抛物线插值」的数值模型（2026-10-01）

用途（改算法前先重算期望值, 纪律 = SK-037）:
  1. 预测插值后 SF/S2/S3 **应该报多少** —— 写给 tb / 文档 / 板测判据;
  2. 与 RTL 同口径复算, 保证"期望值不是拍脑袋"。

与 `self_fft_1024.v` 的对应关系（改 RTL 公式必须同步改这里, 否则金标准失效）:
  - 输入映射 : s = (ad & 0xFF) - 128          ★ 偏移二进制->补码 = **减 128**
      (第一版写成"把字节当补码读"(>=128 就 -256), 等价于给波形注入假谐波,
       结果峰值跑到 3 倍频上 —— 与 2026-09-28 那个输入映射 bug 同类, 已修正。
       记住: 偏移二进制的唯一正确读法是 v-128, 等价于 ad^0x80。)
  - 加窗     : x = (s * w[n]) >> 7             (Q15 Hann 表 src/hann_1024.hex)
  - 幅值     : L1 模 |re|+|im|                 (与找峰/0x8E 压缩同一口径)
  - 找峰     : 正半轴 bin 1..511; 第 2/3 峰须离已选峰 **>=6 bin** 且幅度 **>= 主峰/8**
  - 插值     : δ = 0.5*(c-a)/(2b-a-c)  →  f = (k+δ)*fs/N
               (RTL 里 δ 用 Q8 定标 + 减法循环除法, 与这里等价到 ±0.5Hz)

结论（本文件跑出来的, 可直接抄进文档/判据）:
  正弦  20.0 周期(整数 bin)  : 977 -> **976.6**  (δ=0, 与插值前逐字一致)
  正弦 1000Hz   (20.480 bin) : 977 -> **999.4**  (误差 2.4% -> 0.06%)
  正弦  20.5 周期            : 977 -> **1001.0** (仿真场景 E)
  方波 1000Hz 基波/3次/5次    : 977/2979/4980 -> **999/2998/4998** (真值 1000/3000/5000)
  → 整数 bin 是天然"负向对照": USE_INTERP=1'b0 时应退回 977 一侧的旧值。
"""
import io
import math

N, FS = 1024, 50000.0
HEX = r'../src/hann_1024.hex'      # [10-01 入库] 本脚本现在就在仓库 hw_analysis/ 里


def load_hann(path=HEX):
    w = [int(t, 16) for t in io.open(path, 'r', encoding='utf-8').read().split()]
    assert len(w) == N, '窗表长度不是 %d' % N
    return w


W = load_hann()


def samples_sin(cycles, mid=128, amp=127):
    return [int(round(mid + amp * math.sin(2 * math.pi * cycles * n / N))) for n in range(N)]


def samples_sq(cycles, mid=128, amp=127):
    return [mid + amp if math.sin(2 * math.pi * cycles * n / N) >= 0 else mid - amp for n in range(N)]


def mag_at(samp, k):
    """指定 bin 的 L1 模（浮点; 标度与 δ 无关）"""
    re = im = 0.0
    for n in range(N):
        x = ((samp[n] & 0xFF) - 128) * W[n] >> 7      # ★ 偏移二进制 -> 补码, 再加窗
        a = -2 * math.pi * k * n / N
        re += x * math.cos(a)
        im += x * math.sin(a)
    return abs(re) + abs(im)


def find_peaks(samp, count=3, gap=6):
    """与 RTL 同法: 3 趟扫描 + GAP + 跳过 bin0"""
    mags = [mag_at(samp, k) for k in range(0, 512)]
    out = []
    for _ in range(count):
        best, bk = -1.0, 0
        for k in range(1, 512):
            if any(abs(k - b) < gap for b in out):
                continue
            if mags[k] > best:
                best, bk = mags[k], k
        out.append(bk)
    return out


def interp(samp, k):
    """抛物线插值: 返回 (δ, f_interp, f_bin)"""
    a, b, c = mag_at(samp, k - 1), mag_at(samp, k), mag_at(samp, k + 1)
    dp = 2 * b - a - c
    d = 0.5 * (c - a) / dp if dp > 1e-9 else 0.0
    return d, (k + d) * FS / N, k * FS / N


def main():
    print('=== 自研 1024 点 FFT 插值预测 (Hann / L1 / GAP=6) ===')
    print('  %-22s %-7s %-10s %-12s %-8s %s' % ('信号', '峰bin', '插值前Hz', '插值后Hz', 'δ', '真值Hz'))
    rows = [
        ('正弦 20.0 周期(整bin)', samples_sin(20.0), 20.0),
        ('正弦 1000Hz',           samples_sin(1000 / 48.828125), 1000.0),
        ('正弦 20.5 周期(simE)',  samples_sin(20.5), 20.5 * FS / N),
        ('正弦 10kHz',            samples_sin(10000 / 48.828125), 10000.0),
        ('正弦 20kHz',            samples_sin(20000 / 48.828125), 20000.0),
    ]
    for name, samp, truth in rows:
        k = find_peaks(samp, 1)[0]
        d, f1, f0 = interp(samp, k)
        print('  %-22s %-7d %-10.0f %-12.1f %-8.3f %.0f' % (name, k, f0, f1, d, truth))

    print()
    print('=== 方波三峰（间隔 >=6bin 且幅度 >=主峰/8）===')
    samp = samples_sq(1000 / 48.828125)
    for i, k in enumerate(find_peaks(samp, 3)):
        d, f1, f0 = interp(samp, k)
        print('  第%d峰: bin=%-4d %-6.0f -> %-7.1f Hz (真值 %d)' % (i + 1, k, f0, f1, 1000 * (2 * i + 1)))
    print()
    print('负向对照: 把 RTL 的 USE_INTERP 改成 1\'b0 重新综合,')
    print('          上面所有"插值后"列都应退回"插值前"列(整数 bin 本来就相同)。')


if __name__ == '__main__':
    main()
