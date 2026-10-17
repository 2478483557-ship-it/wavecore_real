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
# [10-17 修复] 原来是 "xvlog ... | tee log | tail -4" —— 管道让 set -e 只看最后一个命令(tail),
#   xvlog 的失败会被**静默吞掉**。实测: cmd_decoder.v 有语法错(端口列表提前关闭),
#   本脚本当时仍报"通过", 直到 Vivado 综合失败才暴露, 白跑一趟综合。必须显式判错。
cp -f ../../src/wave_feat.v .
cp -f ../../src/wave_nn.v .
xvlog --relax *.v 2>&1 | tee xvlog.log | tail -4
if grep -qiE "ERROR" xvlog.log; then
  echo "[失败] xvlog 报错, 见 xvlog.log :"
  grep -iE "ERROR" xvlog.log | head -5
  exit 1
fi
# 精化阶段同样显式判错(管道也会吞掉 xelab 的失败)
if grep -qiE "^ERROR" xelab.log; then
  echo "[失败] xelab 报错, 见 xelab.log :"
  grep -iE "^ERROR" xelab.log | head -5
  exit 1
fi

echo "[3/3] xelab board_top"
xelab board_top -s board_elab -timescale 1ns/1ps 2>&1 | tee xelab.log | tail -8
echo
echo "==> 若出现 Built simulation snapshot 即通过(端口全部对齐)。"
