//===================================================================
// 模块名   : hann_rom
// 功能     : 1024 点 Hann 窗查表(Q15 峰值32768) —— BRAM ROM
// 说明     : 用 initial+$readmemh 加载(最可靠的块ROM推断法);
//            路径为工程工作目录绝对路径(本机开发用)
// 作者     : WaveCore 队长 | 日期: 2026-09-05
//===================================================================

module hann_rom (
    input  wire        clk,
    input  wire [9:0]  addr,
    output reg  [15:0] wout
);

    (* ram_style = "block" *) reg [15:0] wmem [0:1023];

    initial $readmemh("D:/Verilog_project/wavecore/src/hann_1024.hex", wmem);

    always @(posedge clk)
        wout <= wmem[addr];

endmodule
