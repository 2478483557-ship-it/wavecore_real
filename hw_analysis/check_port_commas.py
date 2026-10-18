# -*- coding: utf-8 -*-
"""检查 Verilog 模块端口列表里的逗号位置。

2026-10-17~18 的教训：给模块加端口时，用脚本在「最后一行端口」后追加,
很容易把逗号插到**注释后面**（`... // 说明,`），逗号被注释吃掉 -> 语法错误。
这个坑我犯了 5 次，每次都要靠编译才发现。所以做成静态检查。

判据: 端口列表里, 除最后一项外, 每一项都应以 `,` 结尾（注释之后不算）。
"""
import io
import re
import sys


def check(path):
    src = io.open(path, encoding='utf-8', errors='replace').read()
    lines = src.split('\n')
    # 找 module ... ( 到 匹配的 ) 之间的部分
    m = re.search(r'\bmodule\s+\w+\s*\(', src)
    if not m:
        return 0
    i = src[:m.end()].count('\n')
    depth = 1
    j = i
    body = []
    while j < len(lines) and depth > 0:
        depth += lines[j].count('(') - lines[j].count(')')
        if depth > 0:
            body.append((j, lines[j]))
        j += 1

    errs = 0
    # 只挑像是端口声明(含 input/output/inout)的行
    ports = [(n, l) for n, l in body if re.search(r'\b(input|output|inout)\b', l)]
    for idx, (n, l) in enumerate(ports):
        # 去掉注释
        code = re.sub(r'//.*$', '', l).rstrip()
        if not code:
            continue
        is_last = (idx == len(ports) - 1)
        has_comma = code.endswith(',')
        if is_last and has_comma:
            print('  L%d: 最后一项不该有逗号 -> %s' % (n + 1, l.strip()))
            errs += 1
        if (not is_last) and (not has_comma):
            print('  L%d: 缺逗号（逗号可能被注释吃掉了）-> %s' % (n + 1, l.strip()))
            errs += 1
    return errs


if __name__ == '__main__':
    files = sys.argv[1:]
    total = 0
    for f in files:
        e = check(f)
        total += e
        if e == 0:
            print('%-28s 端口逗号 OK' % f.split('/')[-1])
    sys.exit(1 if total else 0)
