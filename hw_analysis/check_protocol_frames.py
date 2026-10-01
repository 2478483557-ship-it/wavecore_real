# -*- coding: utf-8 -*-
"""
从 board/uart_protocol.md 里把**所有** HEX 命令帧抠出来，逐条复核:
  1) 帧头是 5A A5
  2) LEN 字段与实际负载长度一致
  3) 校验和 == (TYPE+LEN_H+LEN_L+PAYLOAD) 取低 8 位
  4) 0x85 / 0x87 帧把负载按小端解回 Hz, 打印出来供人眼核对

为什么要有这个脚本:
  项目约定"新增命令要同步更新帧速查表并逐条复核校验和"。人眼复核 20 条十六进制
  必然会漏 —— 本脚本就是那条约定的执行体。2026-09-30 用它抓出 37.5kHz 那一行
  把小端字节写成了 9C 92(实际是 37532Hz), 正确应为 7C 92。

用法: python check_protocol_frames.py
返回: 0 = 全过; 1 = 有问题(会打印问题行号)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(HERE, "..", "board", "uart_protocol.md")   # [10-01 入库] 本脚本现在就在仓库 hw_analysis/ 里

# 匹配形如 5A A5 85 00 04 E8 03 00 00 74 的帧(至少 6 个字节)
FRAME_RE = re.compile(r"\b(5A\s+A5(?:\s+[0-9A-Fa-f]{2}){4,})\b")

TYPE_NAME = {
    0x81: "预设档位",
    0x83: "请求波形",
    0x85: "任意频率",
    0x87: "第二频率",
    0x88: "波形选择",
    0x89: "触发模式",
    0x8A: "自研FFT运行",
    0x8B: "扫频",
}


def main():
    if not os.path.exists(DOC):
        print("找不到协议文档:", DOC)
        return 1

    lines = open(DOC, encoding="utf-8").read().splitlines()
    total = bad = 0
    for ln, line in enumerate(lines, 1):
        for m in FRAME_RE.finditer(line):
            raw = m.group(1)
            bs = [int(x, 16) for x in raw.split()]
            total += 1

            problems = []
            if len(bs) < 6:
                problems.append("太短")
            else:
                typ = bs[2]
                n = (bs[3] << 8) | bs[4]
                if len(bs) != 5 + n + 1:
                    problems.append("长度不符: LEN=%d 但实际负载 %d 字节" % (n, len(bs) - 6))
                else:
                    s = sum(bs[2:-1]) & 0xFF
                    if s != bs[-1]:
                        problems.append("校验和错: 应为 %02X, 文档写 %02X" % (s, bs[-1]))

            info = ""
            if not problems and typ in (0x85, 0x87) and ((bs[3] << 8) | bs[4]) == 4:
                hz = bs[5] | (bs[6] << 8) | (bs[7] << 16) | (bs[8] << 24)
                info = "  -> %s = %d Hz" % (TYPE_NAME.get(typ, "?"), hz)
            elif not problems:
                info = "  -> %s" % TYPE_NAME.get(typ, "0x%02X" % typ)

            flag = "  !! " + "; ".join(problems) if problems else "  OK "
            if problems:
                bad += 1
            print("L%-4d %-30s %s%s" % (ln, raw, flag, info if not problems else ""))

    print("-" * 74)
    print("共检查 %d 条帧, 有问题 %d 条" % (total, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
