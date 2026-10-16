# -*- coding: utf-8 -*-
"""生成 1024 点 Blackman 窗查表（Q15 无符号，峰值 32768 = 1.0）。
约定与 gen_hann_rom.py 完全一致，便于两者互换。
输出：
  src/blackman_1024.hex      —— 供综合版 blackman_rom.v 的 $readmemh 读取
  src/blackman_rom.v         —— 综合用（BRAM + $readmemh）
  sim/fft_check/blackman_rom.v —— 仿真用（纯 case 表，避免绝对路径依赖）
"""
import io, math, os

N = 1024
w = [int(round((0.42 - 0.5 * math.cos(2 * math.pi * i / N)
                + 0.08 * math.cos(4 * math.pi * i / N)) * 32768)) for i in range(N)]
w = [0 if x < 0 else (32768 if x > 32768 else x) for x in w]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1) hex
io.open(os.path.join(ROOT, 'src', 'blackman_1024.hex'), 'w', encoding='ascii', newline='\n').write(
    '\n'.join('%04X' % x for x in w) + '\n')

# 2) 综合版
syn = '''//===================================================================
// 模块名   : blackman_rom
// 功能     : 1024 点 Blackman 窗查表, Q15 无符号 (峰值=32768=1.0)
// 副瓣     : -58 dB (Hann -31 dB / 矩形 -13 dB) —— 泄漏抑制最强, 主瓣最宽
// 生成脚本 : hw_analysis/gen_blackman_rom.py (勿手改)
// 作者     : WaveCore 队长 | 日期: 2026-10-16
//===================================================================

module blackman_rom (
    input  wire        clk,
    input  wire [9:0]  addr,
    output reg  [15:0] wout
);

    (* ram_style = "block" *) reg [15:0] wmem [0:1023];

    initial $readmemh("D:/Verilog_project/wavecore/src/blackman_1024.hex", wmem);

    always @(posedge clk)
        wout <= wmem[addr];

endmodule
'''
io.open(os.path.join(ROOT, 'src', 'blackman_rom.v'), 'w', encoding='utf-8', newline='\n').write(syn)

# 3) 仿真版（case 表）
L = []
L.append('// [仿真用] blackman_rom 纯 case 表版本 —— 与 src/blackman_rom.v 数值等价,')
L.append('// 避免 $readmemh 依赖开发机绝对路径。生成: hw_analysis/gen_blackman_rom.py')
L.append('module blackman_rom (')
L.append('    input  wire [9:0]  addr,')
L.append('    output reg  [15:0] wout')
L.append(');')
L.append('    always @(*) begin')
L.append('        case (addr)')
for i in range(N):
    L.append("            10'd%d: wout = 16'd%d;" % (i, w[i]))
L.append('            default: wout = 16\'d0;')
L.append('        endcase')
L.append('    end')
L.append('endmodule')
io.open(os.path.join(ROOT, 'sim', 'fft_check', 'blackman_rom.v'), 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')

print('Blackman 窗已生成:')
print('  点数 %d  峰值 %d  首值 %d  中点 %d' % (len(w), max(w), w[0], w[512]))
print('  副瓣理论对比: 矩形 -13dB / Hann -31dB / Blackman -58dB')
