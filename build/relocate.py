# -*- coding: utf-8 -*-
"""把源码里写死的 ROM 初始化绝对路径改到当前工程位置。

背景
----
5 个 ROM 模块用 $readmemh 读 .hex，路径写死成：

    D:/Verilog_project/wavecore/src/hann_1024.hex

换一台机器、或把工程放到别的目录，综合时就读不到这些文件。
严重的是：读不到时综合**可能不报错**，ROM 全成 X / 0，
上板后波形全错，而你不会知道原因。

涉及文件
--------
    src/hann_rom.v       hann_1024.hex
    src/blackman_rom.v   blackman_1024.hex
    src/sine_rom.v       sine_256.hex
    src/twiddle_rom.v    tw_cos.hex / tw_sin.hex
    src/wave_nn.v        nn_w1.hex / nn_w2.hex / nn_b1.hex / nn_b2.hex

用法
----
    # 先看会改什么，不落盘
    python build/relocate.py --root D:/Verilog_project/wavecore

    # 确认后真正执行
    python build/relocate.py --root D:/Verilog_project/wavecore --apply

    # 换成别的工程位置
    python build/relocate.py --root E:/work/wavecore --apply

    # 改回仓库里的相对默认值（README 推荐的交付形态）
    python build/relocate.py --to-relative --apply

为什么默认是 dry-run
--------------------
改路径本身没风险，风险在「改成一个综合时找不到的路径」。
所以默认只打印，让你先看 diff。
"""
import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")

# 老的写死前缀（两种斜杠都兼容）
OLD_PREFIX_RE = re.compile(r"D:/Verilog_project/wavecore/src/", re.IGNORECASE)


READMEMH_RE = re.compile(
    r'\$readmemh\("D:/Verilog_project/wavecore/src/([A-Za-z0-9_.]+)"',
    re.IGNORECASE,
)


def rewrite(text, new_prefix):
    """把绝对路径前缀换成 new_prefix，返回 (新文本, 被改的文件名列表)。

    注意：不能用 re.sub 的 lambda 去记 changed —— 那样只能记到一次，
    也容易写漏。用 subn 拿次数，用 findall 拿文件名，两件事分开做。
    """
    names = READMEMH_RE.findall(text)
    new_text = READMEMH_RE.sub(lambda m: '$readmemh("%s%s"' % (new_prefix, m.group(1)), text)
    return new_text, names


def collect(text):
    return READMEMH_RE.findall(text)


def main():
    ap = argparse.ArgumentParser(description="重写 ROM 初始化文件的绝对路径")
    ap.add_argument("--root", help="工程根目录，如 D:/Verilog_project/wavecore")
    ap.add_argument("--to-relative", action="store_true",
                    help="改成仅文件名（配合 README 的相对路径约定）")
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认只预览）")
    args = ap.parse_args()

    if not args.to_relative and not args.root:
        ap.error("要么给 --root，要么用 --to-relative")

    if args.root:
        prefix = args.root.rstrip("/\\").replace("\\", "/") + "/src/"
    else:
        prefix = ""

    if not os.path.isdir(SRC):
        print("找不到 src 目录:", SRC)
        return 1

    total_files = 0
    total_hits = 0
    print("目标前缀: %s" % (prefix if prefix else "(仅文件名)"))
    print()

    for name in sorted(os.listdir(SRC)):
        if not name.lower().endswith((".v", ".sv")):
            continue
        p = os.path.join(SRC, name)
        try:
            text = io.open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue

        hits = collect(text)
        if not hits:
            continue

        new_text, changed = rewrite(text, prefix)
        total_files += 1
        total_hits += len(changed)
        print("  %s  (%d 处)" % (name, len(changed)))
        for f in changed:
            print("       -> %s%s" % (prefix, f))

        if args.apply:
            io.open(p, "w", encoding="utf-8", newline="\n").write(new_text)

    print()
    if total_files == 0:
        print("没有找到写死绝对路径的 $readmemh。可能已经改过了。")
        return 0

    print("共 %d 个文件 / %d 处。" % (total_files, total_hits))
    if args.apply:
        print("已写盘。")
        print()
        print("下一步：重新综合，并确认综合日志里没有")
        print("  'WARNING: [Synth 8-6014] ... could not be opened' 之类的 readmem 警告")
        print("然后在板上确认 V / SF 与之前一致 —— 这是 ROM 真的被加载了的证据。")
    else:
        print("这是预览。确认无误后加 --apply 真正执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
