# -*- coding: utf-8 -*-
# 生成 256x8 无符号正弦查找表 dds_rom.v (case 语句实现, 无需 .mem 文件)
import math

out = []
out.append("//===========================================================================")
out.append("// 模块名   : sine_rom")
out.append("// 功能     : 256 x 8bit 正弦查找表 (相位 -> 幅度)")
out.append("// 说明     : 用 case 语句写成的组合逻辑 ROM,")
out.append("//            不依赖 .coe/.mem 文件, 仿真与综合行为完全一致,")
out.append("//            不存在路径找不到数据文件的问题(见 skill/SK-004)。")
out.append("//            生成脚本: hw_analysis/gen_sine_rom.py(勿手改本文件)")
out.append("// 作者     : WaveCore 队长 | 日期: 2026-09-02 | 版本: v1.0")
out.append("//===========================================================================")
out.append("")
out.append("module sine_rom (")
out.append("    input  wire [7:0] addr,   // 相位 0~255 对应 0~359 度")
out.append("    output reg  [7:0] dout    // 正弦幅度 0~255, 直流中心 128")
out.append(");")
out.append("")
out.append("    always @(*) begin")
out.append("        case (addr)")

for i in range(256):
    v = int(round(128 + 127 * math.sin(2 * math.pi * i / 256)))
    if v > 255: v = 255
    if v < 0:   v = 0
    out.append(f"            8'd{i:>3}: dout = 8'd{v:>3};")

out.append("            default: dout = 8'd128;")
out.append("        endcase")
out.append("    end")
out.append("")
out.append("endmodule")
out.append("")

import os
# [10-01 入库时可移植化] 从脚本位置反推仓库根, 不再写死开发机路径
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "sine_rom.v")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("written:", path, "lines:", len(out))

# 顺手校验几个关键点
vals = [int(round(128 + 127*math.sin(2*math.pi*i/256))) for i in range(256)]
print("addr 0   ->", vals[0],  "(应为 128)")
print("addr 64  ->", vals[64], "(应为 255)")
print("addr 128 ->", vals[128],"(应为 128)")
print("addr 192 ->", vals[192],"(应为 1)")
print("min/max  :", min(vals), max(vals))
