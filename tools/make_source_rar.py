# -*- coding: utf-8 -*-
"""重新打包源代码 rar。

为什么要脚本而不是手动拖
------------------------
三个坑，手动打包一定踩：
1. `wavecore/wavecore/` 是 9-02 留下的空壳旧克隆（36 个文件），绝不能进包
2. `.git/` 体积大且对评委无用
3. `__pycache__`、`*.pyc`、Vivado 的 `.runs/.cache/.gen` 全是产物

用法
----
    python tools/make_source_rar.py            # 试跑，只报数量不打包
    python tools/make_source_rar.py --write    # 真的打包
"""
import os
import shutil
import subprocess
import sys
import tempfile

RAR = r"D:/Other application/WinRAR/Rar.exe"
REPO = r"C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore"
# [10-30] 桌面目录会被改名/搬家（这次从 Desktop/嵌赛文件 变成了
#   Desktop/2026嵌赛fpga赛道文件/嵌赛文件）。硬编码会让 rar 报 code 9
#   并且错误信息还是 GBK 乱码，很难看出是路径问题。改成自动探测。
def _resolve_out():
    import os as _os
    for _c in (r"C:/Users/Lenovo/Desktop/2026嵌赛fpga赛道文件/嵌赛文件",
               r"C:/Users/Lenovo/Desktop/嵌赛文件"):
        if _os.path.isdir(_c):
            return _os.path.join(_c, "WaveCore_源代码.rar")
    _d = r"C:/Users/Lenovo/Desktop"
    try:
        for _n in _os.listdir(_d):
            _p = _os.path.join(_d, _n)
            if _os.path.isdir(_p) and "嵌赛" in _n:
                _q = _os.path.join(_p, "嵌赛文件")
                return _os.path.join(_q if _os.path.isdir(_q) else _p,
                                     "WaveCore_源代码.rar")
    except OSError:
        pass
    return r"C:/Users/Lenovo/Desktop/WaveCore_源代码.rar"


OUT = _resolve_out()
TOP = "WaveCore_src"

# 顶层要收的目录（白名单，比黑名单安全）
INCLUDE_DIRS = ["board", "build", "data", "host", "hw_analysis",
                "report", "sim", "skill", "src", "tools"]
INCLUDE_FILES = ["README.md", "LICENSE", ".gitattributes", ".gitignore"]

# 任何层级都跳过的
SKIP_NAMES = {".git", "__pycache__", ".idea", ".vscode",
              "wavecore.runs", "wavecore.cache", "wavecore.gen",
              "wavecore.hw", "wavecore.sim", "wavecore.srcs",
              "wavecore.ip_user_files",
              # [10-26] xsim 编译目录：里面是 xsimk.exe 和 .sdb 中间产物，
              #   两个 sim 目录加起来 5MB+，对评委毫无意义。
              "xsim.dir", "xsim.cache", "xsim.work", ".Xil"}
SKIP_EXT = {".pyc", ".pyo", ".swp", ".swo", ".wdb", ".jou", ".log",
            ".str", ".pb",
            # xsim 编译数据库 / 可执行 / 仿真波形
            ".sdb", ".exe", ".dll", ".so", ".vcd", ".wlf", ".wcfg"}


def want(name, ext):
    # [10-30] 原来写 startswith(".git")，把 **.gitignore / .gitattributes**
    #   也一起排除了 —— 根目录那两个因为走 INCLUDE_FILES 才侥幸进包，
    #   但 sim/board_elab/.gitignore 这类子目录里的就漏掉了。
    #   只有目录名恰好等于 ".git" 才是版本库。
    if name in SKIP_NAMES or name == ".git":
        return False
    if ext.lower() in SKIP_EXT:
        return False
    if name.endswith("~"):
        return False
    return True


def collect():
    files = []
    for d in INCLUDE_DIRS:
        root = os.path.join(REPO, d)
        if not os.path.isdir(root):
            print("  [跳过] 目录不存在: %s" % d)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [x for x in dirnames if want(x, "")]
            for f in filenames:
                if want(f, os.path.splitext(f)[1]):
                    files.append(os.path.join(dirpath, f))
    for f in INCLUDE_FILES:
        p = os.path.join(REPO, f)
        if os.path.isfile(p):
            files.append(p)
    # [10-26] 文档草稿不进源码包：4.85MB，且桌面上另有独立的文档包。
    #   源码包只放"能复现这个工程"需要的东西。
    files = [f for f in files
             if os.path.basename(f) not in ("tech_doc_draft.docx",)
             or not f.endswith(".docx")]
    return files


def main():
    write = "--write" in sys.argv

    files = collect()
    print("=" * 62)
    print("  待打包 %d 个文件" % len(files))
    print("=" * 62)

    # 保险：确认旧壳没被收进来
    bad = [f for f in files if os.path.normpath("/wavecore/wavecore/") in
           "/" + os.path.relpath(f, REPO).replace("\\", "/")]
    if bad:
        print("  ★ 有 %d 个文件来自旧壳 wavecore/wavecore/，必须排除！" % len(bad))
        for b in bad[:3]:
            print("     ", os.path.relpath(b, REPO))
        return 1

    by_dir = {}
    for f in files:
        rel = os.path.relpath(f, REPO).replace("\\", "/")
        top = rel.split("/")[0] if "/" in rel else "(根)"
        by_dir[top] = by_dir.get(top, 0) + 1
    for k in sorted(by_dir, key=lambda x: -by_dir[x]):
        print("  %-14s %3d" % (k, by_dir[k]))

    total_mb = sum(os.path.getsize(f) for f in files) / 1048576
    print("  %-14s %.2f MB" % ("合计", total_mb))

    if not write:
        print()
        print("  试跑结束。确认无误后加 --write 真正打包。")
        return 0

    # ---- 复制到临时目录，保持顶层 WaveCore_src/ ----
    tmp = tempfile.mkdtemp(prefix="wc_pack_")
    dst_root = os.path.join(tmp, TOP)
    try:
        for f in files:
            rel = os.path.relpath(f, REPO)
            dst = os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(f, dst)

        # ---- 打包 ----
        if os.path.exists(OUT):
            os.remove(OUT)
        cmd = [RAR, "a", "-r", "-ep1", "-m3", "-idq", OUT, TOP]
        print()
        print("  打包中...")
        r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                           errors="ignore")
        if r.returncode != 0:
            print("  ★ rar 失败 (code %d)" % r.returncode)
            print((r.stderr or r.stdout)[-400:])
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 校验 ----
    r2 = subprocess.run([RAR, "lb", OUT], capture_output=True, text=True,
                        errors="ignore")
    listed = [x for x in r2.stdout.splitlines() if x.strip()]
    size_mb = os.path.getsize(OUT) / 1048576
    print()
    print("=" * 62)
    print("  已生成: %s" % OUT)
    print("  %d 个文件，%.2f MB" % (len(listed), size_mb))
    has_shell = any("wavecore\\wavecore" in x or "wavecore/wavecore" in x
                    for x in listed)
    print("  含旧壳: %s" % ("★是（异常）" if has_shell else "否"))
    print("  顶层目录: %s" % sorted({x.replace("\\", "/").split("/")[0]
                                    for x in listed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
