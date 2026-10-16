//===================================================================
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
