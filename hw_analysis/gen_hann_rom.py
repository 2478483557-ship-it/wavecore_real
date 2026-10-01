# -*- coding: utf-8 -*-
# 生成 1024x16 无符号 Hann 窗查表 (Q15: 0~32768, 1.0=32768)
import math
N = 1024
out = []
out.append("//===================================================================")
out.append("// 模块名   : hann_rom")
out.append("// 功能     : 1024 点 Hann 窗查表, Q15 无符号 (峰值=32768=1.0)")
out.append("// 用法     : 窗后样点 = 样点(有符号16) * w / 2^15")
out.append("// 生成脚本 : hw_analysis/gen_hann_rom.py (勿手改)")
out.append("// 作者     : WaveCore 队长 | 日期: 2026-09-05")
out.append("//===================================================================")
out.append("")
out.append("module hann_rom (")
out.append("    input  wire [9:0] addr,")
out.append("    output reg  [15:0] wout   // 0~32768")
out.append(");")
out.append("")
out.append("    always @(*) begin")
out.append("        case (addr)")
for i in range(N):
    w = 0.5 * (1.0 - math.cos(2 * math.pi * i / N))
    v = int(round(w * 32768))
    out.append(f"            10'd{i:>4}: wout = 16'd{v:>5};")
out.append("            default: wout = 16'd0;")
out.append("        endcase")
out.append("    end")
out.append("")
out.append("endmodule")
out.append("")
import os
# [10-01 入库时可移植化] 从脚本位置反推仓库根, 不再写死开发机路径
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "hann_rom.v")
open(p, "w", encoding="utf-8").write("\n".join(out))
open(r"D:/Verilog_project/wavecore/src/hann_rom.v", "w", encoding="gbk").write("\n".join(out))
print("Q15 Hann ROM 生成+同步完成")
