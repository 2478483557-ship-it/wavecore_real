# -*- coding: utf-8 -*-
"""修除法器: 商的位置随被除数有效位变化, 必须右移到最低位。

原理: 恢复余数法循环 W 次(W=被除数位宽), 商占 W 位且对齐在低位。
      我把循环固定成 40 次, 但被除数只有十几位有效 -> 只有最后十几拍产生有效商位,
      前面 27 拍都在移 0, 于是商被"抬高"了 27 位, 取低 16 位就是 0。

修法: 装载时把被除数**左对齐**到 bit39（即左移 (40-位宽)），
      这样第一次比较就对应商的最低位, 40 拍得到右对齐的商。
      位宽用 leading-zero 检测。
"""
import io

P = 'src/wave_feat.v'
t = io.open(P, encoding='utf-8').read()

# 1) 加 leading-zero 与前移量计算
old1 = """    wire [40:0] dv_sh = {dv_r[38:0], dv_nsh[39]};   // 移入 N 的最高位
    wire        dv_ge = (dv_sh[39:0] >= {14'd0, dv_d});"""
new1 = """    wire [40:0] dv_sh = {dv_r[38:0], dv_nsh[39]};   // 移入 N 的最高位
    wire        dv_ge = (dv_sh[39:0] >= {14'd0, dv_d});

    // [10-17 修复·关键] 被除数必须**左对齐到 bit39** 再逐位移入。
    //   原来直接装右对齐的值: 被除数只有十几位有效, 前 27 拍都在移 0,
    //   商被抬高 27 位, 取低 16 位就是 0（实测第一次除法 idx=0 得 0, 后面的却对,
    //   因为后面的被除数位宽不同, 抬高的量不同, 恰好低 16 位还有值）。
    //   用 leading-zero 求左移量, 让装载值最高有效位落在 bit39。
    function [5:0] lzc40(input [39:0] v);
        integer i;
        begin
            lzc40 = 6'd40;
            for (i = 39; i >= 0; i = i - 1)
                if (v[i] && lzc40 == 6'd40) lzc40 = 39 - i;
        end
    endfunction
    wire [5:0] dv_sht = lzc40(dv_n);                  // 需要左移的位数
    wire [39:0] dv_ld = dv_n << dv_sht;               // 左对齐后的被除数"""
if old1 not in t:
    raise SystemExit('除法器锚点未命中')
t = t.replace(old1, new1, 1)

# 2) 所有 dv_nsh 装载改为 dv_ld(组合), 不再用 dv_n
t = t.replace("dv_nsh <= {18'd0, sx_abs} << 5;", "dv_nsh <= ({18'd0, sx_abs} << 5) << lzc40({18'd0, sx_abs} << 5);")
t = t.replace("dv_nsh <= {20'd0, a_sl} << 6;", "dv_nsh <= ({20'd0, a_sl} << 6) << lzc40({20'd0, a_sl} << 6);")
t = t.replace("dv_nsh <= {24'd0, sq_cap} << 10;", "dv_nsh <= ({24'd0, sq_cap} << 10) << lzc40({24'd0, sq_cap} << 10);")
t = t.replace("dv_nsh <= a_x4;", "dv_nsh <= a_x4 << lzc40(a_x4);")
t = t.replace("dv_nsh <= d4 << 25;", "dv_nsh <= (d4 << 25) << lzc40(d4 << 25);")

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('除法器已修: 被除数左对齐')
print('  dv_ld 使用次数:', t.count('lzc40('))
