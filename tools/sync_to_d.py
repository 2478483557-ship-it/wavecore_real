# -*- coding: utf-8 -*-
"""把仓库 src/ 同步到 Vivado 工程目录（自动处理编码差异）。

为什么需要这个：
    仓库里的源码是 **UTF-8 + LF**（git 的正常口径），而 Vivado 工程用的是
    **GBK + CRLF**（Windows 中文环境，Vivado 2020.2 读 UTF-8 中文注释会乱码）。
    两边必须保持内容一致、编码不同 —— 手工复制一定会漏，或者漏了也没人发现。

做的事：
    1. 逐文件比对仓库(src/) 与工程目录，列出：
       · 内容不一致（会被覆盖）
       · 只在仓库有（会被新增）
       · 只在工程目录有（不动，只报告 —— 可能是本地调试文件）
    2. UTF-8 -> GBK 转换（含特殊字符替换，GBK 编不进的字符会换成等价 ASCII）
    3. 写出 CRLF
    4. 写后**回读校验**：重新解码，逐字符比对，不一致就报错退出

用法：
    python tools/sync_to_d.py            # 只比对，不写（默认，安全）
    python tools/sync_to_d.py --write    # 真正同步
    python tools/sync_to_d.py --write --dst "D:/别的位置/src"
    python tools/sync_to_d.py --write --with-host     # 连 host/*.py 一起同步
"""
import argparse
import io
import os
import sys

# GBK 编不进去的常见字符 -> 等价 ASCII。不替换的话整文件同步会失败。
SUBST = {
    "²": "^2", "³": "^3", "×": "x", "÷": "/",
    "→": "->", "←": "<-", "↑": "^", "↓": "v",
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~",
    "±": "+/-", "—": "-", "–": "-", "…": "...",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "μ": "u", "Ω": "ohm",
}

DEFAULT_DST = r"D:/Verilog_project/wavecore/src"
EXTS = (".v", ".hex", ".xdc")


def repo_src_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "src")


def read_text(path):
    """尽量按 utf-8 读，失败退回 gbk。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace").replace("\r\n", "\n")


def to_gbk(text, name):
    """转 GBK 字节；遇到编不进的字符先替换，并报告替换了什么。"""
    fixed = {}
    out = []
    for ch in text:
        try:
            ch.encode("gbk")
            out.append(ch)
        except UnicodeEncodeError:
            rep = SUBST.get(ch)
            if rep is None:
                raise SystemExit(
                    "  [失败] %s 含有 GBK 编不进、又没有替换规则的字符：%r (U+%04X)\n"
                    "        请先在 SUBST 里加一条规则。" % (name, ch, ord(ch))
                )
            fixed[ch] = rep
            out.append(rep)
    return "".join(out), fixed


def sync_host(repo_root, proj_root, write):
    """同步 host/*.py。保持 UTF-8（Python 3 默认按 UTF-8 读，不能转 GBK）。"""
    hsrc = os.path.join(repo_root, "host")
    hdst = os.path.join(proj_root, "host")
    if not (os.path.isdir(hsrc) and os.path.isdir(hdst)):
        print("host/ 目录不存在，跳过")
        return True

    same = diff = add = 0
    changed, failed = [], []
    for f in sorted(os.listdir(hsrc)):
        if not f.endswith(".py"):
            continue
        a_path = os.path.join(hsrc, f)
        b_path = os.path.join(hdst, f)
        a = read_text(a_path)

        if not os.path.exists(b_path):
            add += 1
        elif read_text(b_path) == a:
            same += 1
            continue
        else:
            diff += 1

        if write:
            with open(b_path, "wb") as fh:
                fh.write(a.replace("\n", "\r\n").encode("utf-8"))
            if read_text(b_path) != a:
                failed.append(f)
            else:
                changed.append(f)

    print("host/ 一致 %d 个｜需更新 %d 个｜新增 %d 个" % (same, diff, add))
    if diff or add:
        marks = []
        if changed:
            marks.append("已更新: " + ", ".join(changed))
        if failed:
            marks.append("★ 失败: " + ", ".join(failed))
        if not write:
            marks.append("（只比对，未写入）")
        print("        " + "；".join(marks))
    return not failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="真正写入（默认只比对）")
    ap.add_argument("--dst", default=DEFAULT_DST, help="Vivado src 目录")
    ap.add_argument("--with-host", action="store_true",
                    help="同时同步 host/*.py（保持 UTF-8，Python 不需要 GBK）")
    args = ap.parse_args()

    src = repo_src_dir()
    if not os.path.isdir(src):
        raise SystemExit("找不到仓库 src 目录: %s" % src)
    if not os.path.isdir(args.dst):
        raise SystemExit("找不到工程 src 目录: %s" % args.dst)

    files = sorted(f for f in os.listdir(src) if f.endswith(EXTS))
    same, differ, added, blocked = 0, [], [], []

    for f in files:
        p_src = os.path.join(src, f)
        p_dst = os.path.join(args.dst, f)
        text = read_text(p_src)

        if not os.path.exists(p_dst):
            added.append(f)
        elif read_text(p_dst) == text:
            same += 1
            continue
        else:
            differ.append(f)

        if not args.write:
            continue

        try:
            gbk_text, fixed = to_gbk(text, f)
        except SystemExit as e:
            blocked.append((f, str(e)))
            continue

        with open(p_dst, "wb") as fh:
            fh.write(gbk_text.replace("\n", "\r\n").encode("gbk"))

        # 回读校验：解码回来必须和源逐字符一致（替换掉的字符除外）
        back = read_text(p_dst)
        if back != gbk_text:
            blocked.append((f, "  [失败] %s 回读不一致，写入可能损坏" % f))
        if fixed:
            print("  %-22s 已写入（替换了 %s）"
                  % (f, "、".join("%r→%r" % kv for kv in fixed.items())))

    only_d = sorted(
        f for f in os.listdir(args.dst)
        if f.endswith(EXTS) and f not in set(files)
    )

    print("\n" + "=" * 62)
    print("仓库: %s" % src)
    print("工程: %s" % args.dst)
    print("-" * 62)
    print("一致        : %d 个" % same)
    print("不一致      : %s" % (", ".join(differ) if differ else "无"))
    print("只在仓库有  : %s" % (", ".join(added) if added else "无"))
    print("只在工程有  : %s（不动，仅报告）" % (", ".join(only_d) if only_d else "无"))
    if blocked:
        print("失败        : %s" % ", ".join(f for f, _ in blocked))
        for _, msg in blocked:
            print(msg)
    print("=" * 62)

    if not args.write:
        if args.with_host:
            sync_host(os.path.dirname(src), os.path.dirname(args.dst), False)
        if differ or added:
            print("当前是【只比对】模式。确认无误后加 --write 执行同步。")
        else:
            print("两边已完全一致，无需同步。")
        return 0

    if blocked:
        return 1

    # ---- host/*.py：同样两份，但**保持 UTF-8**（Python 3 默认按 UTF-8 读）----
    #   D 盘的 host/ 是 10-21 的旧副本，用户双击的 run_gui.bat 很可能在那里，
    #   结果"改了代码但界面没变"——10-23 就踩过这个。
    if args.with_host:
        hsrc = os.path.join(os.path.dirname(src), "host")
        hdst = os.path.join(os.path.dirname(args.dst), "host")
        if os.path.isdir(hsrc) and os.path.isdir(hdst):
            n_same = n_diff = n_add = 0
            changed = []
            for f in sorted(os.listdir(hsrc)):
                if not f.endswith(".py"):
                    continue
                a_path = os.path.join(hsrc, f)
                b_path = os.path.join(hdst, f)
                a = read_text(a_path)
                if not os.path.exists(b_path):
                    n_add += 1
                elif read_text(b_path) == a:
                    n_same += 1
                    continue
                else:
                    n_diff += 1
                if args.write:
                    with open(b_path, "wb") as fh:
                        fh.write(a.replace("\n", "\r\n").encode("utf-8"))
                    back = read_text(b_path)
                    if back != a:
                        print("  [失败] host/%s 回读不一致" % f)
                        return 1
                    changed.append(f)
            print("host/ 一致 %d 个，需更新 %d 个，新增 %d 个"
                  % (n_same, n_diff, n_add))
            if args.write and changed:
                print("  已更新: %s" % ", ".join(changed))
        else:
            print("host/ 目录不存在，跳过")

    print("同步完成。别忘了重新综合（rebuild_bitstream.bat）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
