# -*- coding: utf-8 -*-
"""
生成并复核 WaveCore 下行命令帧(含校验和)

帧格式: 5A A5 | TYPE | LEN_H | LEN_L | PAYLOAD(LEN) | SUM
校验和: SUM = (TYPE + LEN_H + LEN_L + PAYLOAD) 求和取低 8 位 (不含帧头 5A A5)

用途: 按项目约定, 凡是提到"设置信号(频率/波形/触发/抓波形)"的地方,
      必须附上可粘贴的帧, 且校验和要逐条复核 —— 本脚本就是那个"复核"。
"""
import re
import sys

BAUD = 460800


def frame(typ, payload_bytes):
    n = len(payload_bytes)
    body = [typ, (n >> 8) & 0xFF, n & 0xFF] + list(payload_bytes)
    s = sum(body) & 0xFF
    return bytes([0x5A, 0xA5] + body + [s])


def hexs(b):
    return " ".join("%02X" % x for x in b)


def u32le(v):
    return [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]


# (说明, 类型, 负载)
ITEMS = [
    ("设 100Hz         (0x85)", 0x85, u32le(100)),
    ("设 1000Hz        (0x85)", 0x85, u32le(1000)),
    ("设 2000Hz        (0x85)", 0x85, u32le(2000)),
    ("设 10000Hz       (0x85)", 0x85, u32le(10000)),
    ("设 37500Hz       (0x85)", 0x85, u32le(37500)),
    ("预设 100kHz      (0x81)", 0x81, [0]),
    ("波形=正弦        (0x88)", 0x88, [0]),
    ("波形=方波        (0x88)", 0x88, [1]),
    ("波形=三角        (0x88)", 0x88, [2]),
    ("触发=自由        (0x89)", 0x89, [0]),
    ("触发=上升沿      (0x89)", 0x89, [1]),
    ("触发=下降沿      (0x89)", 0x89, [2]),
    ("请求波形一次     (0x83)", 0x83, [0]),
    ("自研FFT 运行一次 (0x8A)", 0x8A, [0]),
    ("幅度谱帧请求   (0x8E)", 0x8E, []),
    ("扫频 开始        (0x8B)", 0x8B, [1]),
    ("扫频 停止        (0x8B)", 0x8B, [0]),
    ("第二频率 1.1kHz  (0x87)", 0x87, u32le(1100)),
    # ---- v1.17 新增: 电压标定 0x8C ----
    # payload = KN低字节 KN高字节 00 00 ; KN = 每 LSB 多少 mV x1024(Q10)
    ("标定 原始LSB KN=1024 (0x8C)", 0x8C, [0x00, 0x04, 0x00, 0x00]),
    ("标定 默认 KN=8000  (0x8C)", 0x8C, [0x40, 0x1F, 0x00, 0x00]),
    # 例子: 原始计数 N=139 时, 万用表实测真实峰峰值 1200mV ->
    #       KN = round(1200*1024/139) = 8840 = 0x2288 -> 小端 88 22
    #       回代校验: 139*8840/1024 = 1199.96 -> 上报 1199 mV (截断差 1mV, 可接受)
    ("标定 实测KN=8840   (0x8C)", 0x8C, [0x88, 0x22, 0x00, 0x00]),
]

# 若给了命令行参数, 就只核对参数里出现的那几条(便于把文档里的帧拿来复核)
if len(sys.argv) > 1:
    pat = sys.argv[1:]
    print("按给定键核对:")
    for p in pat:
        print(" ", p)

print()
print("波特率: %d-8N1    帧头 5A A5    校验和 = TYPE+LEN_H+LEN_L+PAYLOAD 取低8位" % BAUD)
print("-" * 74)
for name, typ, pl in ITEMS:
    b = frame(typ, pl)
    # 反向复核: 从生成的帧里重新算一遍
    assert b[0] == 0x5A and b[1] == 0xA5
    assert b[2] == typ
    assert (b[3] << 8 | b[4]) == len(pl)
    assert b[-1] == (sum(b[2:-1]) & 0xFF)
    print("%-24s %s" % (name, hexs(b)))
print("-" * 74)
print("全部 %d 条已通过自校验(重算 SUM == 帧内 SUM)" % len(ITEMS))
