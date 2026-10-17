#!/bin/sh
# wave_feat 特征提取器回归
set -e
cd "$(dirname "$0")"
. ./xenv.sh
echo "[1/3] 同步源码"
cp -f ../../src/wave_feat.v ./wave_feat.v
echo "[2/3] 编译"
rm -rf xsim.dir work
xvlog wave_feat.v tb_wave_feat.v 2>&1 | tee xvlog.log | tail -3
if grep -qiE "ERROR" xvlog.log; then echo "[失败] 编译错误:"; grep -iE "ERROR" xvlog.log|head -5; exit 1; fi
echo "[3/3] 精化 + 仿真"
xelab tb_wave_feat -s feat_sim -timescale 1ns/1ps 2>&1 | tee xelab.log | tail -2
if grep -qiE "^ERROR" xelab.log; then echo "[失败] 精化错误:"; grep -iE "^ERROR" xelab.log|head -5; exit 1; fi
timeout 300 xsim feat_sim -R > xsim_run.log 2>&1 || true
cat xsim_run.log | tr -d '\000'
