//===================================================================
// 模块名   : sine_rom
// 功能     : 256 x 8bit 正弦查找表 (相位 -> 幅度) —— 块 ROM 版
// 说明     : initial+$readmemh 加载 -> 映射 BRAM, 释放 LUT/F7/F8
//            输出比地址晚 1 拍(对 DAC 通路无影响)
// 生成脚本 : hw_analysis/gen_sine_rom.py(勿手改本文件)
// 作者     : WaveCore 队长 | 日期: 2026-09-06 | 版本: v2.0
//===================================================================

module sine_rom (
    input  wire        clk,
    input  wire [7:0]  addr,   // 相位 0~255 对应 0~359 度
    output reg  [7:0]  dout    // 正弦幅度 0~255, 直流中心 128
);

    (* ram_style = "block" *) reg [7:0] mem [0:255];

    initial $readmemh("D:/Verilog_project/wavecore/src/sine_256.hex", mem);

    always @(posedge clk)
        dout <= mem[addr];

endmodule
