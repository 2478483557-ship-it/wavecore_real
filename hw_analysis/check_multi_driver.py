# -*- coding: utf-8 -*-
"""静态检查 Verilog 里的**多驱动**：同一个 reg 被两个不同的 always 块赋值。

为什么需要它：2026-10-17 的 `inv_pend` 就被主状态机的复位分支和一个专用 always
同时赋值，Vivado 把真寄存器**接到 GND**（CRITICAL WARNING 8-6859/8-6858）。
**XSim 对多驱动网的仲裁与综合不同** → 仿真全绿、硬件全死，排查了整整一个上午。

用法:
    python hw_analysis/check_multi_driver.py src/*.v
退出码非 0 表示发现问题。
"""
import re
import sys

def blocks_of(text):
    """把每个 always 块抽出来, 返回 [(起始行号, 块文本)]。用 begin/end 配平 + 单语句兜底。"""
    out = []
    for m in re.finditer(r'\balways\b', text):
        i = m.start()
        j = text.find('\n', i)
        rest = text[j:]
        # 跳过 @(...) 敏感列表
        k = 0
        if rest.lstrip().startswith('@'):
            k = rest.index(')') + 1 if ')' in rest else 0
        tail = rest[k:].lstrip()
        if tail.startswith('begin'):
            depth, p = 0, text.index('begin', j + k)
            while p < len(text):
                if text.startswith('begin', p):
                    depth += 1; p += 5
                elif text.startswith('end', p):
                    depth -= 1; p += 3
                    if depth == 0:
                        break
                else:
                    p += 1
            body = text[i:p + 3]
        else:
            # 单语句: 到第一个分号
            body = text[i:text.index(';', i) + 1]
        out.append((text[:i].count('\n') + 1, body))
    return out


def check(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    text = re.sub(r'//[^\n]*', '', text)          # 去行注释
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    # reg 声明
    regs = set(re.findall(r'\breg\b(?:\s+signed)?\s*(?:\[[^\]]*\])?\s*(\w+)', text))
    assign_map = {}
    for lineno, body in blocks_of(text):
        for lhs in re.findall(r'(\w+)\s*<=', body):
            assign_map.setdefault(lhs, set()).add(lineno)
    bad = {k: v for k, v in assign_map.items()
           if len(v) > 1 and (k in regs or not regs)}
    return bad


def main():
    files = sys.argv[1:]
    if not files:
        print('用法: python check_multi_driver.py src/*.v')
        return 2
    total = 0
    for f in files:
        bad = check(f)
        if bad:
            total += len(bad)
            print('[多驱动] %s' % f)
            for sig, lines in sorted(bad.items()):
                print('    %-18s 被 %d 个 always 块赋值, 行号 %s'
                      % (sig, len(lines), sorted(lines)))
    if total:
        print('\n共发现 %d 个多驱动信号 —— **综合会保留常量驱动, 把真寄存器接到 GND**' % total)
        print('修法: 只让一个 always 块驱动它(通常把复位从主状态机里挪走)。')
        return 1
    print('多驱动检查通过: 没有信号被两个 always 块同时赋值')
    return 0


if __name__ == '__main__':
    sys.exit(main())
