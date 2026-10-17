#!/bin/sh
# wave_nn 推理核回归 (Vivado 2020.2 XSim)
set -e
cd "$(dirname "$0")"
. ./xenv.sh
echo "[1/3] 同步仓库 src/"
cp -f ../../src/wave_nn.v ./wave_nn.v
echo "[2/3] 编译"
rm -rf xsim.dir work
xvlog wave_nn.v tb_wave_nn.v 2>&1 | tee xvlog.log | tail -2
echo "[3/3] 精化 + 仿真"
xelab tb_wave_nn -s nn_sim -timescale 1ns/1ps 2>&1 | tee xelab.log | tail -2
if timeout 240 xsim nn_sim -R > xsim_run.log 2>&1; then cat xsim_run.log
else echo "!! xsim 未正常结束, 日志 $(wc -c < xsim_run.log) 字节"; exit 1; fi
