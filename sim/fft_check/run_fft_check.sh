#!/bin/sh
# ===========================================================================
# self_fft_1024 三峰判据回归仿真 (Vivado 2020.2 XSim, Git Bash)
#   用法: bash run_fft_check.sh
# 说明: 直接调 unwrapped/*.exe, 环境变量见 xenv.sh
#       命令行里 PATH 必须写 /d/... 形式, 写 D:/... 会被 MSYS 当路径分隔符切坏
# ===========================================================================
set -e
cd "$(dirname "$0")"
. ./xenv.sh

echo "[0/4] 同步被测源码 (以仓库 src/ 为准)"
cp -f ../../src/self_fft_1024.v ./self_fft_1024.v

echo "[1/4] 生成激励表"
"C:/Users/Lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe" gen_tables.py

echo "[2/4] 编译"
rm -rf xsim.dir work
xvlog self_fft_1024.v twiddle_rom.v blk_mem_gen_1.v tb_self_fft.v 2>&1 | tee xvlog.log

echo "[3/4] 精化"
xelab tb_self_fft -s tb_sim -timescale 1ns/1ps 2>&1 | tee xelab.log

echo "[4/4] 仿真"
xsim tb_sim -R 2>&1 | tee xsim_run.log
