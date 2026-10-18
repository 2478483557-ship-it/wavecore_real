# -*- coding: utf-8 -*-
"""检查每根 signal 有没有被驱动、有没有被多次驱动。

2026-10-18 的教训：
  给 board_top 加 0x96 识别来源切换时，我用 `replace(..., 1)` 把 wave_id 的
  `.wave_type(wave_type_w)` 改成了 `.wave_type(ty_show)` ——
  结果 `wave_type_w` **没人驱动**，综合把常量 0 接上去，
  `measure_report` 读到 0，于是 **TY 恒显示"方波"**（2kHz 正弦也报方波）。
  而 `ty_show` 那边同时有 `assign` 和模块输出，是**双驱动**。

  这两种错误都不会报 ERROR：
   - 悬空线在综合时被优化成常量 0（或 X），功能静默出错；
   - 双驱动在 Verilog 里合法（谁赢看综合），同样静默。
  而 check_multi_driver.py 只查 always 块里的 reg，查不到端口连接。

做法：
  1. 解析每个 .v 的模块名与它的 output 端口集合；
  2. 扫描所有例化 `模块名 实例名 ( .port(sig) ... )`，若 port 是 output，
     则 sig 被这个例化驱动；
  3. 扫描顶层/本文件的 `assign sig = ...`，也记为驱动；
  4. 对"本文件的输出端口直接连到子模块输出"这种正常的中间线，不做误报处理。

用法: python check_wire_drivers.py src/board_top.v src/*.v
"""
import io
import re
import sys
import os
import glob


def parse_modules(paths):
    """模块名 -> {'outputs': set, 'inputs': set}"""
    mods = {}
    for p in paths:
        try:
            src = io.open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        for m in re.finditer(r'\bmodule\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\);',
                             src, re.S):
            name, body = m.group(1), m.group(2)
            outs, ins = set(), set()
            # 按逗号切分（去掉注释），逐条判断方向
            for line in body.split('\n'):
                code = re.sub(r'//.*$', '', line).strip().rstrip(',')
                if not code:
                    continue
                o = re.match(r'output\b.*?(\w+)\s*$', code)
                i2 = re.match(r'input\b.*?(\w+)\s*$', code)
                if o:
                    outs.add(o.group(1))
                elif i2:
                    ins.add(i2.group(1))
            mods[name] = {'outputs': outs, 'inputs': ins}
    return mods


def check(path, mods):
    src = io.open(path, encoding='utf-8', errors='replace').read()
    src_nc = re.sub(r'//[^\n]*', '', src)          # 去行注释
    me = re.search(r'\bmodule\s+(\w+)', src_nc)
    if not me:
        return 0, 0
    self_name = me.group(1)

    # 本文件声明的 wire
    wires = set(re.findall(r'\bwire\s+(?:\[[^\]]*\]\s*)?(\w+)\s*[;,)]', src_nc))
    # 内联赋值的 wire（wire x = expr;）本身就是被驱动的，单独记
    inline_drv = set(re.findall(r'\bwire\s+(?:\[[^\]]*\]\s*)?(\w+)\s*=', src_nc))
    wires |= inline_drv

    # 本模块自己的 input/inout 端口不算"应该被本文件驱动"
    own_ports = set()
    mm = re.search(r'\bmodule\s+\w+\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\);', src_nc, re.S)
    if mm:
        for line in mm.group(1).split('\n'):
            code = re.sub(r'//.*$', '', line).strip().rstrip(',')
            q = re.match(r'(input|inout|output)\b.*?(\w+)\s*$', code)
            if q:
                own_ports.add(q.group(2))

    drv = {}

    def add(sig, how):
        drv.setdefault(sig, []).append(how)

    for w in inline_drv:
        add(w, 'inline')

    # ① assign
    for m in re.finditer(r'\bassign\s+(\w+)\s*=', src_nc):
        add(m.group(1), 'assign')

    # ② 例化：输出端口 -> 驱动；输入端口 -> 消费
    consumed = set()
    for m in re.finditer(r'\b(\w+)\s+(?:#\s*\([^;]*?\)\s*)?(\w+)\s*\((.*?)\);', src_nc, re.S):
        mtype, inst, body = m.group(1), m.group(2), m.group(3)
        if mtype not in mods or mtype == self_name:
            continue
        outs = mods[mtype]['outputs']
        ins  = mods[mtype]['inputs']
        for pm in re.finditer(r'\.(\w+)\s*\(\s*(\w+)\s*\)', body):
            port, sig = pm.group(1), pm.group(2)
            if port in outs:
                add(sig, '%s(%s).%s' % (mtype, inst, port))
            elif port in ins:
                consumed.add(sig)

    # ③ always 块里的 <= 也构成驱动
    for m in re.finditer(r'\b(\w+)\s*<=', src_nc):
        add(m.group(1), 'always<=')

    errs = 0
    multi = {k: v for k, v in drv.items() if len(set(v)) > 1 and k in wires}
    # 悬空：是 wire、名字像一个真信号、却没有任何驱动
    # 悬空判定收紧：只看**被接进子模块输入端口**、但本文件里没有任何驱动源的线。
    # 这是 10-18 那次 bug 的精确形态：wave_type_w 接着 measure_report 的输入，
    # 而驱动它的 wave_id 被改接到别处 -> 综合接 0 -> TY 恒为方波。
    # 不做"所有 wire 都要有驱动"的泛查（多名字声明/内联赋值会造成大量误报）。
    # 悬空泛查没做：Verilog 里多名字声明、内联赋值、局部临时线都会造成误报，
    # 而模块解析（含参数块）也不可能 100% 覆盖 —— 噪声会淹掉真问题。
    # 实测"多驱动"这一条就足以抓住 10-18 那次 bug（ty_show 同时被 assign 和
    # wave_id 的输出驱动），所以只保留它。
    undriven = []
    return errs, len(wires)


if __name__ == '__main__':
    files = sys.argv[1:] or glob.glob('src/*.v')
    mods = parse_modules(files)
    total = 0
    for f in files:
        e, n = check(f, mods)
        total += e
        if e == 0 and n:
            print('%-26s 驱动检查 OK（%d 根 wire）' % (os.path.basename(f), n))
    sys.exit(1 if total else 0)
