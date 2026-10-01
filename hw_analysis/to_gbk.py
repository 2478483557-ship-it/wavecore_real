# -*- coding: utf-8 -*-
# 把仓库里的 UTF-8 .v 源码转成 GBK 副本放到 Vivado 工程(见 skill/SK-001)
import os

# [10-01 入库时可移植化] 从脚本位置反推仓库根, 不再写死开发机路径
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dst  = r"D:/Verilog_project/wavecore/src"
files = [
    ("src/dds_nco.v",       "dds_nco.v"),
    ("src/sine_rom.v",      "sine_rom.v"),
    ("src/dds_top.v",       "dds_top.v"),
    ("sim/tb_dds_top.v",    "tb_dds_top.v"),
]
for rel, name in files:
    src_path = os.path.join(repo, rel)
    txt = open(src_path, "r", encoding="utf-8").read()
    gbk_path = os.path.join(dst, name)
    with open(gbk_path, "w", encoding="gbk", errors="strict") as f:
        f.write(txt)
    print("GBK written:", gbk_path, os.path.getsize(gbk_path), "bytes")
