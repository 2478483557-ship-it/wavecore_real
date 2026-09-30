# -*- coding: utf-8 -*-
"""
oracle.py —— vpp_mv / measure_report v3.3 期望值的**独立复算**(Python)

作用: Verilog testbench 里的期望值是手写的, 手写就可能抄错。
      这里用完全独立的语言(Python) 再算一遍, 两边对上才算数。
      **注意: 本脚本不参与自动判定**, 它只打印一张对照表供人工/交叉核对。

用法: python oracle.py
"""

# ---------- ① vpp_mv: mv = floor(vpp_lsb * KN / 1024) ----------
CASES = [
    # (vpp_lsb, KN, 备注)
    (0,   8000,  "零点"),
    (139, 8000,  "正弦自测 Vpp 典型值"),
    (111, 8000,  "方波自测 Vpp 典型值"),
    (255, 8000,  "满量程"),
    (139, 1024,  "KN=1024 -> 原始 LSB 透传"),
    (255, 1024,  "KN=1024 满量程"),
    (1,   1024,  "KN=1024 最小非零"),
    (200, 20000, "19.53 mV/LSB"),
    (100, 512,   "0.5 mV/LSB"),
    (255, 65535, "饱和检查"),
    (255, 0,     "KN=0 边界"),
]

print("=" * 68)
print("① vpp_mv 换算表   mv = (vpp_lsb * KN) >> 10, 饱和到 9999")
print("=" * 68)
print("%8s %8s %10s %10s  %s" % ("lsb", "KN", "raw", "显示", "备注"))
for lsb, kn, note in CASES:
    raw = (lsb * kn) >> 10
    disp = min(raw, 9999)
    print("%8d %8d %10d %10d  %s" % (lsb, kn, raw, disp, note))

print()
print("  推导: KN=8000 -> 8000/1024 = 7.8125 mV/LSB -> 满量程 256*7.8125 = 2000 mV")
print("        所以上电默认按 '0~2V 量程' 显示; 这是假设值, 需万用表标定。")


# ---------- ② measure_report v3.3 整帧构造 ----------
def frame(freq, vpp_lsb, kn, duty_x10, width_us, wave_type, prev_f):
    """返回 (46 字节 bytes, ty_now)"""
    mv = (vpp_lsb * kn) >> 10
    mv = min(mv, 9999)

    # TY 稳定闸门: 频率 >25kHz, 或相对上一帧跳变过大 -> 判为"其他(3)"
    ty = wave_type
    if freq > 25000:
        ty = 3
    elif prev_f != 0 and abs(freq - prev_f) > (prev_f // 64 + 16):
        ty = 3

    s = ""
    s += "F=%07dHz V=%04d\r\n" % (freq, mv)
    s += "D=%03d.%d%% W=%05dus\r\n" % (duty_x10 // 10, duty_x10 % 10, width_us)
    s += "TY=%d\r\n" % ty
    return s.encode("ascii"), ty


print()
print("=" * 68)
print("② measure_report v3.3 期望帧   (V 为 mV, 4 位)")
print("=" * 68)

SCEN = [
    # tag, freq, lsb, kn,   duty_x10, width_us, type, prev_f
    (1, 1000,  139, 8000, 500,  500,   1, 0),
    (2, 1000,  139, 1024, 500,  500,   1, 1000),
    (3, 12345, 255, 8000, 1234, 12345, 0, 1000),
    (4, 12345, 255, 8000, 1234, 12345, 0, 12345),
]

prev = 0
for tag, f, lsb, kn, d, w, ty_in, prev_f in SCEN:
    data, ty = frame(f, lsb, kn, d, w, ty_in, prev_f)
    pretty = data.decode("ascii").replace("\r\n", "<CR><LF>\n")
    pretty = pretty.replace("\n", "<LF>")          # 剩下的裸 LF(本协议没有)
    pretty = pretty.replace("<LF>", "")            # 上面是防御性检查, 正常应为空
    print("场景%d  freq=%d  vpp=%dLSB  KN=%d  -> len=%d  TY=%d" % (tag, f, lsb, kn, len(data), ty))
    print("       V 字段 = %d mV" % min((lsb * kn) >> 10, 9999))
    print(pretty)

print()
print("字节下标对照(前 20 个):")
data, _ = frame(1000, 139, 8000, 500, 500, 1, 0)
for i in range(20):
    c = data[i]
    print("  [%2d] 0x%02X  %s" % (i, c, repr(chr(c)) if 32 <= c < 127 else "<控制字符>"))
print("  总长度 = %d 字节" % len(data))
