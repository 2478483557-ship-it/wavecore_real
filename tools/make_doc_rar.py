# -*- coding: utf-8 -*-
"""重打文档包（三个 PDF）。

为什么需要脚本
--------------
文档包和源码包一样容易过期，而且是**最容易被忘的那个**：
源码改了会想着重打，PDF 重新生成了却常常忘了重新装包。

上一次就是这个情况 —— 三个 PDF 都更新到 10-26 中午，
但 `WaveCore_文档.rar` 还停在 10-24，里面是旧的 25 页版。

用法
----
    python tools/make_doc_rar.py            # 试跑，检查三个 PDF 在不在、多新
    python tools/make_doc_rar.py --write    # 真正打包
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

RAR = r"D:/Other application/WinRAR/Rar.exe"
SRC = r"C:/Users/Lenovo/Desktop/嵌赛文件"
OUT = os.path.join(SRC, "WaveCore_文档.rar")
TOP = "WaveCore_文档"

# (桌面上现在的文件名, 包内编号文件名)
ITEMS = [
    ("技术文档_WaveCore.pdf",     "1_技术文档_WaveCore.pdf"),
    ("工程技能包_WaveCore.pdf",   "2_工程技能包_WaveCore.pdf"),
    ("大模型协作记录_WaveCore.pdf", "3_大模型协作记录_WaveCore.pdf"),
]


def main():
    write = "--write" in sys.argv

    print("=" * 62)
    print("  文档包")
    print("=" * 62)

    missing = []
    files = []
    for src_name, dst_name in ITEMS:
        p = os.path.join(SRC, src_name)
        if not os.path.isfile(p):
            missing.append(src_name)
            continue
        st = os.stat(p)
        files.append((p, dst_name, st.st_size / 1048576,
                      time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))))

    print("  %-34s %-8s %s" % ("文件", "大小", "修改时间"))
    print("  " + "-" * 56)
    for src, dst, mb, mt in files:
        print("  %-34s %6.2f MB  %s" % (dst, mb, mt))

    if missing:
        print()
        print("  ★ 缺文件: %s" % ", ".join(missing))
        print("    先在桌面 嵌赛文件/ 里把 PDF 生成出来")
        return 1

    old = None
    if os.path.exists(OUT):
        old = time.strftime("%m-%d %H:%M",
                            time.localtime(os.path.getmtime(OUT)))
        print()
        print("  现有包: %s（%d 天前）"
              % (old, (time.time() - os.path.getmtime(OUT)) // 86400))

    if not write:
        print()
        print("  试跑结束。确认无误后加 --write 真正打包。")
        return 0

    tmp = tempfile.mkdtemp(prefix="wc_doc_")
    try:
        dst_root = os.path.join(tmp, TOP)
        os.makedirs(dst_root, exist_ok=True)
        for src, dst, _, _ in files:
            shutil.copy2(src, os.path.join(dst_root, dst))

        if os.path.exists(OUT):
            os.remove(OUT)
        print()
        print("  打包中...")
        r = subprocess.run([RAR, "a", "-r", "-m3", "-idq", OUT, TOP],
                           cwd=tmp, capture_output=True, text=True,
                           errors="ignore")
        if r.returncode != 0:
            print("  ★ rar 失败 (code %d)" % r.returncode)
            print((r.stderr or r.stdout)[-400:])
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 校验：把包里的文件列出来 ----
    r2 = subprocess.run([RAR, "lb", OUT], capture_output=True)
    raw = r2.stdout
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            listed = raw.decode(enc).splitlines()
            break
        except UnicodeDecodeError:
            continue

    print()
    print("=" * 62)
    print("  已生成: %s" % OUT)
    print("  %d 个条目，%.2f MB"
          % (len([x for x in listed if x.strip()]),
             os.path.getsize(OUT) / 1048576))
    for x in listed:
        if x.strip().endswith(".pdf"):
            print("    ", x.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
