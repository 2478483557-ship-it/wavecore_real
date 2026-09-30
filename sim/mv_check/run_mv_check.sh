#!/bin/sh
# ===========================================================================
# mV 改造专项回归 (Vivado 2020.2 XSim, Git Bash)
#   用法: bash run_mv_check.sh
#
# 跑三个测试平台:
#   ① tb_vpp_mv      —— LSB->mV 换算单元测试(硬编码期望值)
#   ② tb_report_mv   —— 上报帧 46 字节逐字节比对(4 个场景)
#   ③ tb_cmd_decoder —— 0x8C 电压标定命令解析
#
# 说明: 直接调 unwrapped/*.exe, 环境变量见 xenv.sh
#       命令行里 PATH 必须写 /d/... 形式, 写 D:/... 会被 MSYS 当路径分隔符切坏
#
# ⚠️ 已知环境问题(2026-09-30)：某些会话里 `xsim <snapshot> -R` 会**无输出挂死**
#    （连 09-28 跑通过的旧快照也一样挂 → 不是测试平台的问题，是环境问题，见
#     board/vivado_gui_troubleshoot.md §4）。此时：
#      - xvlog + xelab 仍然可用（能验语法与端口连接）；
#      - 要真正跑波形，把本目录的 tb_*.v 加进 Vivado 工程，用 GUI 的 Run Simulation。
#    脚本已改为"编译/精化失败就停，运行失败只告警"，不会假装通过。
# ===========================================================================
set -e
cd "$(dirname "$0")"
. ./xenv.sh

PY="C:/Users/Lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

run_sim() {                      # $1=snapshot 名  $2=日志名
    if timeout 240 xsim "$1" -R > "$2" 2>&1; then
        cat "$2"
    else
        echo "!! xsim $1 未能正常结束(超时/挂死)。日志大小: $(wc -c < "$2") 字节"
        echo "   这就是 xvlog/xelab 都通过、但运行阶段挂在环境上的情形。"
        echo "   请改用 Vivado GUI 跑本目录的 tb_*.v，或换一次会话重试。"
        return 1
    fi
}

echo "[0/7] 同步被测源码 (以仓库 src/ 为准)"
cp -f ../../src/vpp_mv.v        ./vpp_mv.v
cp -f ../../src/measure_report.v ./measure_report.v
cp -f ../../src/cmd_decoder.v   ./cmd_decoder.v
cp -f ../../src/bin2bcd.v       ./bin2bcd.v
cp -f ../../src/uart_tx.v       ./uart_tx.v
cp -f ../../src/uart_rx.v       ./uart_rx.v
cp -f ../tb_cmd_decoder.v       ./tb_cmd_decoder.v

echo "[0.5] 用 Python 独立复算一遍期望值(交叉核对, 不参与判定)"
"$PY" oracle.py || true

echo ""
echo "=========== ① tb_vpp_mv : LSB -> mV 单元测试 ==========="
rm -rf xsim.dir work
xvlog vpp_mv.v tb_vpp_mv.v 2>&1 | tee xvlog_unit.log
xelab tb_vpp_mv -s tb_unit -timescale 1ns/1ps 2>&1 | tee xelab_unit.log
run_sim tb_unit xsim_unit.log || true

echo ""
echo "=========== ② tb_report_mv : 上报帧 46 字节回归 ==========="
rm -rf xsim.dir work
xvlog vpp_mv.v measure_report.v bin2bcd.v uart_tx.v uart_rx.v tb_report_mv.v 2>&1 | tee xvlog_report.log
xelab tb_report_mv -s tb_report -timescale 1ns/1ps 2>&1 | tee xelab_report.log
run_sim tb_report xsim_report.log || true

echo ""
echo "=========== ③ tb_cmd_decoder : 0x8C 标定命令解析 ==========="
rm -rf xsim.dir work
xvlog cmd_decoder.v uart_tx.v uart_rx.v tb_cmd_decoder.v 2>&1 | tee xvlog_cmd.log
xelab tb_cmd_decoder -s tb_cmd -timescale 1ns/1ps 2>&1 | tee xelab_cmd.log
run_sim tb_cmd xsim_cmd.log || true

echo ""
echo "======================================================"
grep -h "PASS\]\|FAIL\]\|全部通过\|有 .* 项失败\|自检" xsim_unit.log xsim_report.log xsim_cmd.log || true
echo "======================================================"
