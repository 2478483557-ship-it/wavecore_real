#!/bin/sh
# ===========================================================================
# fft_demo 等价性回归: 新版(v3.3 块RAM) vs 旧版(32768 个触发器)
#   用法: bash run_equiv.sh
# 判据: 两版 [STUB] 行的 chk_xor / chk_sum / fb 全一致 -> 数据通路等价
# 说明: 直接调 unwrapped/*.exe, 环境变量见 xenv.sh
#       命令行 PATH 必须写 /d/... 形式, 写 D:/... 会被 MSYS 切坏
#       两版串行跑, 跑完一版清一次 xsim.dir, 避免互相覆盖
# ===========================================================================
cd "$(dirname "$0")"
. ./xenv.sh

PASS=1

run_one () {          # $1 = 标签, $2 = 被测 fft_demo 源文件
    tag=$1
    src=$2
    echo "############ [$tag] $src ############"
    rm -rf xsim.dir .Xil xsim.jou webtalk*.jou webtalk*.log
    # --relax: 工程源码里有"先用后声明"(如 win_out), Vivado 综合容忍,
    #          xvlog 严格模式会报 VRFC 10-3380。两版都用同一开关, 保证公平。
    xvlog --relax "$src" hann_rom.v xfft_stub.v tb_fft_demo.v > "xvlog_$tag.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "!! xvlog 失败, 见 xvlog_$tag.log"; tail -20 "xvlog_$tag.log"; return 1
    fi
    xelab tb_fft_demo -s "sim_$tag" -timescale 1ns/1ps > "xelab_$tag.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "!! xelab 失败, 见 xelab_$tag.log"; tail -20 "xelab_$tag.log"; return 1
    fi
    xsim "sim_$tag" -R > "sim_$tag.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "!! xsim 返回非 0(可能挂死), 见 sim_$tag.log"; return 1
    fi
    grep -E "^\[STUB\]|^\[TB\]" "sim_$tag.log" > "out_$tag.txt"
    echo "---- $tag 输出 ----"
    cat "out_$tag.txt"
    return 0
}

echo "[1/3] 同步被测源码"
cp -f ../../src/fft_demo.v ./fft_demo_new.v

echo "[2/3] 跑旧版(HEAD 快照)"
run_one old fft_demo_old.v || PASS=0

echo "[3/3] 跑新版(v3.3)"
run_one new fft_demo_new.v || PASS=0

echo "=========================================="
if [ "$PASS" -eq 1 ] && diff -u out_old.txt out_new.txt > diff_out.txt 2>&1; then
    echo "PASS: 新旧两版样点流完全一致 (chk_xor/chk_sum/fb/done 全等)"
    rm -f diff_out.txt
    exit 0
else
    echo "FAIL: 两版不一致(或某版没跑完), 差异如下"
    [ -f diff_out.txt ] && cat diff_out.txt
    exit 1
fi
