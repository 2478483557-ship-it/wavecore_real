//===================================================================
// 模块名   : invwin_rom
// 功能     : 1024 点**逆窗**查表(Q12) —— 用于反变换后的包络补偿
// 说明     : 频谱是在加 Hann 窗的数据上算的，反变换回来的时域 = 原信号 x 窗。
//            回放时乘上本表的 1/max(hann,0.25)，就能把纺锤形恢复成等幅。
//            表由 hw_analysis/gen_invwin.py 从实际的 hann_1024.hex 推出，
//            增益 1.00~4.00 倍(两端封顶在 4 倍，各约 170 点)。
// 作者     : WaveCore 队长 | 日期: 2026-10-17
//===================================================================

module invwin_rom (
    input  wire        clk,
    input  wire [9:0]  addr,
    output reg  [15:0] iwout
);

    (* ram_style = "block" *) reg [15:0] iwmem [0:1023];

    initial $readmemh("D:/Verilog_project/wavecore/src/invwin_1024.hex", iwmem);

    always @(posedge clk)
        iwout <= iwmem[addr];

endmodule
