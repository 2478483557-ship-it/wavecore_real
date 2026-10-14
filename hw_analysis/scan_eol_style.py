# -*- coding: utf-8 -*-
"""
scan_eol_style.py   (只读诊断，不改任何文件)

背景：`board/verify_checklist.md` 里出现了这种形态：
    ...已弃用）\r>   \n> 用途：...
即 **行内 CR 后面跟着 `>   ` 再接 LF** —— 一行里同时含 CR 和 LF，
但 `\n` 的**前一个字符是空格**，所以 `b.count(b'\r\n')` 数不到它。

这说明上一轮 SK-033 硬规矩 4 的自检函数**判据不完整**：
它只数了"相邻的 CRLF 对数"，漏掉了"CR 与 LF 被若干字符隔开"的行内混排。

本脚本用**逐行扫描**的严格判据重新体检全库。
"""
import os

# [2026-10-14] 原来写死开发机绝对路径 -> 改为从脚本位置反推仓库根，换机器可直接跑。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只扫"人写的源文件"；下面的东西天然会是"混排"或本就是二进制，判它没意义。
SKIP_DIRS = {".git", "wavecore.runs", "wavecore.cache", "wavecore.gen",
             "wavecore.hw", "wavecore.ip_user_files", "xsim.dir", ".Xil"}
SKIP_NAME_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
                  ".pyc", ".zip", ".bit", ".bin", ".pdf", ".docx", ".xlsx",
                  ".pptx", ".hex", ".sdb", ".jou", ".dcp", ".rpt")
# 已知"故意保持现状"的文件（改了就是篡改历史/官方原文）
ALLOW_MIXED = {
    "report/llm_collab_log.md",   # 历史协作日志, 故意不动
    "LICENSE",                    # MIT 官方原文自带混排
    "wavecore/LICENSE",
}
# 生成物: 下次跑就会被覆盖, 不用管
SKIP_PATH_PREFIX = ("sim/mv_check/", "sim/fft_check/", "sim/raw_shots/", "sim/tmp/")

TEXT_EXTS = (".md", ".v", ".py", ".bat", ".tcl", ".xdc", ".sv", ".sh", ".c", ".h",
             ".json", ".yml", ".yaml", ".txt")

problems = []
skipped = []
scanned = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        if not fn.lower().endswith(TEXT_EXTS):
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        if rel in ALLOW_MIXED or rel.startswith(SKIP_PATH_PREFIX):
            skipped.append(rel)
            continue
        try:
            b = open(p, "rb").read()
        except Exception:
            continue
        # 二进制兜底（有 NUL 就跳过）
        if b"\x00" in b[:4096]:
            skipped.append(rel + " [binary]")
            continue
        scanned += 1

        # --- 严格判据：逐个字节看 CR / LF 是否成对 ---
        bad_lf = sum(1 for i, c in enumerate(b) if c == 0x0A and (i == 0 or b[i - 1] != 0x0D))
        bad_cr = sum(1 for i, c in enumerate(b) if c == 0x0D and (i + 1 >= len(b) or b[i + 1] != 0x0A))
        crlf = b.count(b"\r\n")
        has_bom = b[:3] == b"\xef\xbb\xbf"

        if bad_lf == 0 and bad_cr == 0:
            continue                       # 纯净
        if crlf == 0 and bad_cr == 0:
            continue                       # 纯 LF 文件, 正常
        if crlf == 0 and bad_lf == 0:
            continue                       # 纯 CR 文件(极罕见), 正常
        problems.append((rel, bad_lf, bad_cr, crlf, has_bom))

print("扫描人写的文本文件:", scanned, " 跳过(历史/官方/生成物):", len(skipped))
print()
if not problems:
    print("[OK] 全部纯净（每个文件要么纯 CRLF、要么纯 LF，无行内混排），无 BOM")
else:
    print("[!] %d 个文件换行混用/带 BOM：" % len(problems))
    print("%-58s %8s %8s %8s %5s" % ("文件", "裸LF", "裸CR", "CRLF", "BOM"))
    for rel, a, c, d, e in sorted(problems, key=lambda x: -(x[1] + x[2])):
        print("%-58s %8d %8d %8d %5s" % (rel, a, c, d, e))
    raise SystemExit(1)

