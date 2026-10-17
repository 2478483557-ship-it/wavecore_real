# -*- coding: utf-8 -*-
"""检查"脉冲型输出"是否在时钟块默认区每拍清零。

2026-10-17 的教训：cmd_decoder 的 dbg_read 只在复位分支赋过 0，
正常工作时被 0x94 置 1 后**再也回不到 0**，于是上报模块被无限重触发，
串口一直刷 SF/S2/S3，用户只能拔电。

凡是"收到命令拉高 1 拍"的信号，都必须在 `else begin` 之后、解析逻辑之前
无条件赋 0；否则它一旦被置 1 就永远卡住。

用法: python hw_analysis/check_pulse_clear.py src/cmd_decoder.v [...]
退出码非 0 表示发现缺失。
"""
import io, re, sys

PULSE_RE = re.compile(r'(_set|_load|_req|_run|_go|_start|_done|dbg_read)$')


def check(path):
    t = io.open(path, encoding='utf-8').read()
    sigs = [m.group(1) for m in re.finditer(
        r'output\s+reg\s+(?:\[[^\]]*\]\s*)?(\w+)', t) if PULSE_RE.search(m.group(1))]
    if not sigs:
        return []
    i_else = t.find("        else begin")
    if i_else < 0:
        return []
    # 默认区 = else begin 之后到第一个 if 语句之前
    nxt = t.find("            if (", i_else)
    zone = t[i_else: nxt if nxt > 0 else len(t)]
    return [s for s in sigs if not re.search(r'\b%s\s*<=\s*1\'b0' % s, zone)]


def main():
    bad_total = 0
    for f in sys.argv[1:]:
        bad = check(f)
        print('%-28s 脉冲型输出 %s' % (f, ('缺默认清零: ' + ', '.join(bad)) if bad else 'OK'))
        bad_total += len(bad)
    if bad_total:
        print('\n共 %d 个信号会永久卡 1 —— 在时钟块默认区补 `sig <= 1\'b0;`' % bad_total)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
