#!/bin/sh
set -e
cd "$(dirname "$0")"
. ./xenv.sh
cp -f ../../src/spec_avg.v ./spec_avg.v
rm -rf xsim.dir work
xvlog spec_avg.v tb_spec_avg.v 2>&1 | tee xvlog.log | tail -2
if grep -qiE "^ERROR" xvlog.log; then echo "[失败] 编译错误"; exit 1; fi
xelab tb_spec_avg -s avg_sim -timescale 1ns/1ps 2>&1 | tee xelab.log | tail -2
if grep -qiE "^ERROR" xelab.log; then echo "[失败] 精化错误"; exit 1; fi
timeout 120 xsim avg_sim -R > xsim_run.log 2>&1 || true
cat xsim_run.log | tr -d '\000'
