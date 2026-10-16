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
cp -f ../../src/hann_rom.v     ./hann_rom.v
cp -f ../../src/blackman_rom.v ./blackman_rom.v      # [10-16] 自适应窗新增
cp -f ../../src/spec_compress.v ./spec_compress.v   # [0x8E] 谱帧压缩器(self_fft 新例化)

# ---- 窗表一致性断言(2026-09-30 加 Hann 窗后新增; 10-16 加 Blackman) --------
# hann_rom.v / blackman_rom.v 里写的是 $readmemh("D:/Verilog_project/wavecore/src/xxx.hex", ...)
# 即**工程绝对路径**。如果工程里那份和仓库 src/ 那份不一样, 仿真就是在拿另一张
# 表做验证 —— 结论看着对, 其实测的不是仓库里的代码(SK-024 的坑)。
for T in hann_1024 blackman_1024; do
  if ! cmp -s ../../src/$T.hex /d/Verilog_project/wavecore/src/$T.hex; then
    echo "[错误] 工程的 $T.hex 与仓库 src/ 不一致!"
    echo "       先跑: python hw_analysis/sync_src_gbk.py  再重跑本脚本"
    exit 1
  fi
done
echo "       窗表一致性: OK (hann + blackman, 仓库 src/ == 工程 src/)"

echo "[1/4] 生成激励表"
"C:/Users/Lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe" gen_tables.py

echo "[2/4] 编译"
rm -rf xsim.dir work
xvlog self_fft_1024.v spec_compress.v hann_rom.v blackman_rom.v twiddle_rom.v blk_mem_gen_1.v tb_self_fft.v 2>&1 | tee xvlog.log

echo "[3/4] 精化"
xelab tb_self_fft -s tb_sim -timescale 1ns/1ps 2>&1 | tee xelab.log

echo "[4/4] 仿真"
xsim tb_sim -R 2>&1 | tee xsim_run.log
