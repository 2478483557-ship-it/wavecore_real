//===========================================================================
// 模块名   : dual_tone
// 功能     : 双音模式控制 —— 0x87 设第二频率后开启"双音合成";
//           任何单音设定(按键/0x81/0x85)自动退回单音
// 作者     : WaveCore 队长 | 日期: 2026-09-05 | 版本: v1.0
//===========================================================================

module dual_tone (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        single_chg,   // 单音设定脉冲(来自 freq_ctrl)
    input  wire        dual_load,    // 0x87 双音命令脉冲(来自 cmd_decoder)
    input  wire [31:0] dual_fcw,     // 第二频率 fcw
    output reg         dual,         // 1=双音模式
    output reg  [31:0] fcw2          // 第二路 NCO 的 fcw
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dual  <= 1'b0;
            fcw2  <= 32'd0;
        end
        else if (dual_load) begin
            dual <= 1'b1;
            fcw2 <= dual_fcw;
        end
        else if (single_chg) begin
            dual <= 1'b0;            // 任何单音设定 -> 回单音
        end
    end

endmodule
