# -*- coding: utf-8 -*-
"""把仓库 host/ 同步到 D 盘工程目录（Vitado 工程旁边那份）。

为什么需要它：2026-10-17 一整天，上位机与一键工具的改动都留在仓库副本里，
而用户在 D 盘运行的是旧版（10-14），因此"功能明明改了却看不到"。
**src/*.v 有 sync_src_gbk.py 负责，host/ 之前没人管** —— 这是那个漏洞的补丁。

用法:  python hw_analysis/sync_host.py
"""
import os, shutil, filecmp, sys

SRC = r'C:/Users/Lenovo/WorkBuddy/2026-09-02-11-10-14/wavecore/host'
DST = r'D:/Verilog_project/wavecore/host'
EXT = ('.py', '.bat')

def main():
    if not os.path.isdir(SRC) or not os.path.isdir(DST):
        print('目录不存在: %s 或 %s' % (SRC, DST)); return 1
    new, upd, same = 0, 0, 0
    for f in sorted(os.listdir(SRC)):
        if not f.endswith(EXT):
            continue
        s, d = os.path.join(SRC, f), os.path.join(DST, f)
        if os.path.exists(d):
            if filecmp.cmp(s, d, shallow=False):
                same += 1; continue
            shutil.copy2(s, d); print('  更新 %s' % f); upd += 1
        else:
            shutil.copy2(s, d); print('  新增 %s' % f); new += 1
    print('同步完成: 更新 %d / 新增 %d / 未变 %d' % (upd, new, same))
    print('目标: %s' % DST)
    return 0

if __name__ == '__main__':
    sys.exit(main())
