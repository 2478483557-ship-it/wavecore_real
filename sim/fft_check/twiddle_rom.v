//===========================================================================
// 模块名   : twiddle_rom  (自研FFT旋转因子表)
// 功能     : 1024 x 16bit 双表(cos / -sin), Q1.15, 块ROM
// 数据     : tw_cos.hex / tw_sin.hex (hw_analysis 生成, 与调度金标准一致)
// 作者     : WaveCore 队长 | 2026-09-16
//===========================================================================
module twiddle_rom (
    input  wire        clk,
    input  wire [9:0]  addr,
    output reg  [15:0] cos_o,
    output reg  [15:0] sin_o
);
    (* ram_style = "block" *) reg [15:0] mem_c [0:1023];
    (* ram_style = "block" *) reg [15:0] mem_s [0:1023];
    initial begin
        $readmemh("D:/Verilog_project/wavecore/src/tw_cos.hex", mem_c);
        $readmemh("D:/Verilog_project/wavecore/src/tw_sin.hex", mem_s);
    end
    always @(posedge clk) begin
        cos_o <= mem_c[addr];
        sin_o <= mem_s[addr];
    end
endmodule
