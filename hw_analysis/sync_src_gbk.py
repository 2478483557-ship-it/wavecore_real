# -*- coding: utf-8 -*-
"""
把仓库 src/ 下的全部文件同步到 Vivado 工程目录, 并转成 GBK。

背景(双轨编码):
  - GitHub 仓库用 UTF-8(跨平台、能上 GitHub)
  - Vivado 2020.2 工程用 GBK(Windows 下中文注释不乱码)
  - 所以每次改完 .v 都要"转一份 GBK 副本"丢进 D 盘工程

用法:
  python sync_src_gbk.py            # 同步(默认整目录)
  python sync_src_gbk.py self_fft_1024.v fft_demo.v   # 只同步指定文件

注意:
  - 只做"仓库 -> 工程"单向同步。工程里的改动请先手工搬回仓库, 否则会被覆盖。
  - 十六进制表(.hex)是纯 ASCII, 一起拷, 不做编码转换但保持行尾一致。
"""
import os
import shutil
import sys

# [10-01 入库时可移植化] 从脚本位置反推仓库根, 不再写死开发机路径
REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
DST_SRC = r"D:/Verilog_project/wavecore/src"

# 纯文本(要转 GBK)的后缀
TEXT_EXT = (".v", ".sv", ".vh", ".xdc", ".tcl")
# 直接二进制拷贝的后缀(纯 ASCII 数据表)
RAW_EXT = (".hex", ".coe", ".mem")


def main():
    if not os.path.isdir(REPO_SRC):
        print("仓库 src 目录不存在:", REPO_SRC)
        return 1
    if not os.path.isdir(DST_SRC):
        print("工程 src 目录不存在:", DST_SRC)
        return 1

    # [2026-10-20 修复·重要] 仓库把约束文件放在 board/，而工程放在 src/，
    #   原来的循环只扫仓库的 src/，于是 **wavecore.xdc 从来没被同步过** ——
    #   工程里那份一直停留在 09-15，比仓库多一行 SPI_BUSWIDTH 4。
    #   后果：从源码包重新综合得到的 bit 与交付的 bit 不一致（x1 vs x4 启动）。
    #   这里补一条显式映射，让约束文件也走同一条同步路径。
    BOARD_SRC = os.path.join(os.path.dirname(REPO_SRC), "board")
    EXTRA_MAP = {"wavecore.xdc": os.path.join(BOARD_SRC, "wavecore.xdc")}

    only = sys.argv[1:]
    names = sorted(os.listdir(REPO_SRC))
    if only:
        names = [n for n in names if n in set(only)]
        # board/ 里映射过来的文件不算"缺失"，否则明明同步成功还打印"跳过"
        missing = set(only) - set(names) - set(EXTRA_MAP.keys())
        for m in sorted(missing):
            print("  [跳过] 仓库里没有:", m)

    n_txt = n_raw = n_skip = 0

    # 先把 board/ 下的约束文件同步过去（见上方注释）
    for dst_name, src_path in EXTRA_MAP.items():
        if only and dst_name not in set(only):
            continue
        if not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(DST_SRC, dst_name)
        txt = open(src_path, "r", encoding="utf-8").read()
        try:
            with open(dst_path, "w", encoding="gbk", errors="strict", newline="\r\n") as f:
                f.write(txt)
            print("  [GBK ] %-28s %6d bytes  (来自 board/)" % (dst_name, len(txt.encode("gbk"))))
            n_txt += 1
        except UnicodeEncodeError as exc:
            print("  [失败] %s 含 GBK 编不了的字符: %s" % (dst_name, exc))

    for name in names:
        sp = os.path.join(REPO_SRC, name)
        if not os.path.isfile(sp):
            continue
        dp = os.path.join(DST_SRC, name)
        ext = os.path.splitext(name)[1].lower()

        if ext in TEXT_EXT:
            txt = open(sp, "r", encoding="utf-8").read()
            # 注释里禁 emoji: GBK 编不了, 会直接抛异常, 这里给出人话提示
            try:
                with open(dp, "w", encoding="gbk", errors="strict", newline="\r\n") as f:
                    f.write(txt)
            except UnicodeEncodeError as e:
                print("  [失败] %-24s 含 GBK 编不了的字符(多半是 emoji): %s"
                      % (name, e.object[e.start:e.end]))
                return 1
            print("  [GBK ] %-24s %d bytes" % (name, os.path.getsize(dp)))
            n_txt += 1

        elif ext in RAW_EXT:
            shutil.copyfile(sp, dp)
            print("  [RAW ] %-24s %d bytes" % (name, os.path.getsize(dp)))
            n_raw += 1

        else:
            n_skip += 1

    print()
    print("同步完成: 文本 %d 个 / 数据 %d 个 / 其他跳过 %d 个" % (n_txt, n_raw, n_skip))
    print("目标目录:", DST_SRC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
