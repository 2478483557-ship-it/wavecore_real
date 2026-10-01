#!/bin/sh
# ===========================================================================
# 整顶层(board_top) 精化检查 —— 不开 Vivado 也能验证"所有例化端口对齐"
#   把全部 src/*.v + 4 个 IP 行为级替身(blk_mem_gen_0/1, xfft_0, ila_0)
#   一起编译并精化 board_top。改了例化/端口后必跑(比等 8~15 分钟综合快得多)。
#   用法: bash run_board_elab.sh
#   通过标志: 最后出现 "Built simulation snapshot"
# ===========================================================================
set -e
cd "$(dirname "$0")"
. ../fft_check/xenv.sh

echo "[1/3] 同步仓库 src/ 与替身"
cp -f ../../src/*.v .
cp -f ../fft_check/blk_mem_gen_1.v .
cp -f ../fft_demo_check/xfft_stub.v ./xfft_0.v
ls blk_mem_gen_0.v ila_0.v >/dev/null

echo "[2/3] xvlog"
rm -rf xsim.dir work
xvlog --relax *.v 2>&1 | tee xvlog.log | tail -4

echo "[3/3] xelab board_top"
xelab board_top -s board_elab -timescale 1ns/1ps 2>&1 | tee xelab.log | tail -8
echo
echo "==> 若出现 Built simulation snapshot 即通过(端口全部对齐)。"
