# -*- coding: utf-8 -*-
"""检查 tkinter grid 布局有没有控件重叠。

2026-10-17 的教训：给控制面板新加了「频谱窗 / 帧重叠 / 频域滤波」三行，
但 `applied_settings_var` 那个标签**本来就在 row=6、columnspan=9**，
直接把整行盖住了 —— 代码在、功能也在，用户却"看不到"。
另有一处 DAC 回放(span 2) 与 NN 识别 同 cell 重叠。

这类问题不影响语法、不影响运行，只影响"能不能看见"，所以必须静态查。

用法: python hw_analysis/check_gui_layout.py host/wavecore_gui.py
"""
import io
import re
import sys


def cells(row, col, span_r, span_c):
    return {(row + r, col + c) for r in range(span_r) for c in range(span_c)}


def main(path):
    src = io.open(path, encoding='utf-8').read()
    lines = src.split('\n')

    # 只统计挂在 controls 上的控件（控制面板），别的容器各自独立
    used = {}          # (row,col) -> [描述]
    problems = []

    # 扫 .grid(...) 调用（可能跨行）
    for m in re.finditer(r'\)?\.grid\s*\(([^)]*)\)', src):
        args = m.group(1)
        r = re.search(r'row\s*=\s*(\d+)', args)
        c = re.search(r'column\s*=\s*(\d+)', args)
        if not r or not c:
            continue
        dr = int(re.search(r'rowspan\s*=\s*(\d+)', args).group(1)) if 'rowspan' in args else 1
        dc = int(re.search(r'columnspan\s*=\s*(\d+)', args).group(1)) if 'columnspan' in args else 1
        row, col = int(r.group(1)), int(c.group(1))

        # 取该 grid 前面 ~6 行作为描述，判断是不是 controls 的
        pos = m.start()
        ctx = src[max(0, pos - 400):pos]
        # 排除 LabelFrame 自身(controls.grid(...) 挂在 root 上, 不属于面板内部)
        if re.search(r'controls\.grid\s*\(', ctx[-120:]):
            continue
        if 'controls' not in ctx and 'self.nn_button' not in ctx and 'self.ifft_stop_button' not in ctx:
            continue
        label = re.findall(r'text\s*=\s*"([^"]{0,24})"', ctx)
        desc = (label[-1] if label else '?') + ' @row%d col%d span(%d,%d)' % (row, col, dr, dc)

        for cell in cells(row, col, dr, dc):
            if cell in used:
                problems.append((cell, used[cell], desc))
            else:
                used[cell] = desc

    # 只报"宽跨列控件盖住别的控件"——这是真正会让功能"看不见"的情形
    #   （2026-10-17: applied_settings 在 row=6 columnspan=9, 把整行新控件盖掉了）
    # 同一个 cell 里的窄控件(如 "~" 压在 spinbox 上) 属于排版细节, 不算错误。
    severe = []
    for cell, a, b in problems:
        def span_of(d):
            m = re.search(r'span\(\d+,(\d+)\)', d)
            return int(m.group(1)) if m else 1
        if span_of(a) >= 3 or span_of(b) >= 3:
            severe.append((cell, a, b))

    print('控制面板共占用 %d 个 grid 单元格' % len(used))
    if severe:
        print('\n发现 %d 处「宽跨列控件盖住其他控件」—— 被盖的功能会看不见:' % len(severe))
        seen = set()
        for cell, a, b in severe:
            k = (a, b)
            if k in seen:
                continue
            seen.add(k)
            print('  row%d col%d : 「%s」 与 「%s」' % (cell[0], cell[1], a, b))
        print('\n修法: 把宽标签挪到所有控件之后的空行。')
        return 1
    print('无「宽标签遮挡」问题 ✓  (共 %d 处同格窄控件, 属排版细节)' % len(problems))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'host/wavecore_gui.py'))
