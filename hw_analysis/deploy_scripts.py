# -*- coding: utf-8 -*-
"""
把仓库里的 Windows 脚本(.bat/.tcl)统一成 CRLF 行尾, 并部署到 Vivado 工程目录。

背景(2026-09-30):
  工程根目录的 rebuild_bitstream.bat / program_device.bat 原本是 UTF-8 + 中文 + LF,
  cmd.exe 按 GBK 读取时中文被误解码, 产生 cmd 当作命令分隔符的字符 ->
  脚本静默跑不完, 而且**从来没成功启动过 Vivado**(rebuild_bitstream.log 一直不存在)。
  => 全部重写成纯 ASCII, 并强制 CRLF 行尾, 再部署。

用法: python deploy_scripts.py          # 转换 + 部署
      python deploy_scripts.py --check  # 只检查(不写)
"""
import io
import os
import sys

# [10-01 入库时可移植化] 原来写死开发机绝对路径, 换台机器就失效; 改成从脚本位置反推仓库根
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = r"D:/Verilog_project/wavecore"

# (仓库内相对路径, 是否同时部署到工程目录)
FILES = [
    ("board/check_lut.bat",            True),
    ("board/rebuild_bitstream.bat",    True),
    ("board/program_device.bat",       True),
    ("board/rebuild_bitstream.tcl",    True),
    ("board/program_device.tcl",       True),
    ("sim/fft_check/run_fft_check.bat",     False),
    ("sim/fft_demo_check/run_equiv.bat",    False),
    ("host/run_gui.bat",                    False),
]

# 只允许 ASCII 可编码的文件
ASCII_ONLY = True


def to_crlf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def main():
    check_only = "--check" in sys.argv
    problems = []

    for rel, deploy in FILES:
        src = os.path.join(REPO, rel)
        if not os.path.isfile(src):
            problems.append("缺文件: " + src)
            continue

        raw = open(src, "rb").read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            problems.append("%s 不是 UTF-8: %s" % (rel, e))
            continue

        if ASCII_ONLY:
            bad = sorted({c for c in text if ord(c) > 127})
            if bad:
                problems.append("%s 含非 ASCII 字符: %r" % (rel, bad[:8]))

        new = to_crlf(text).encode("utf-8")
        changed = new != raw
        flag = "改" if changed else "OK"
        print("  [%s] %-38s %6d B" % (flag, rel, len(new)))

        if check_only or not changed:
            pass
        else:
            open(src, "wb").write(new)

        if deploy and not check_only and os.path.isdir(DST):
            dst = os.path.join(DST, os.path.basename(rel))
            open(dst, "wb").write(new)
            print("        -> deployed to %s" % dst)

    print()
    if problems:
        print("发现问题:")
        for p in problems:
            print("  !!", p)
        return 1
    print("全部为纯 ASCII + CRLF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
