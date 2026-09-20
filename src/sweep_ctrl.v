//===========================================================================
// 模块名   : sweep_ctrl  (扫频控制 v1.0)
// 功能     : 0x8B 使能后, 频率从 F_START 起每 STEP_CYC 拍 +F_STEP Hz,
//            到 F_END 后回卷 F_START, 循环扫描 (给"瀑布图"演示配套)
// 输出     : load(单拍脉冲) + fcw, 走 freq_ctrl 的"任意频率"通道
// 换算     : fcw = f * M >> 24, M = 2^32/50MHz (与 cmd_decoder 一致)
// 作者     : WaveCore 队长 | 日期: 2026-09-20
//===========================================================================
module sweep_ctrl #(
    parameter [23:0] F_START  = 24'd1000,      // 起始 1kHz
    parameter [23:0] F_STEP   = 24'd100,       // 步进 100Hz
    parameter [23:0] F_END    = 24'd20000,     // 终点 20kHz (≤混叠界)
    parameter [31:0] STEP_CYC = 32'd2_500_000  // 每步 50ms
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,          // 0x8B 电平: 1=扫频中
    output reg         load,        // 单拍: 新频率生效
    output reg  [31:0] fcw
);
    localparam [31:0] M = 32'd1_441_150_920;   // fcw/Hz @50MHz

    reg  [31:0] tim;
    reg  [23:0] f_cur;
    reg         en_prev;

    // 下一频率(回卷逻辑)
    wire [23:0] f_next = (f_cur + F_STEP > F_END) ? F_START : (f_cur + F_STEP);
    wire [55:0] mul    = f_next * M;           // 56bit
    wire [31:0] fcw_c  = mul[55:24];           // >>24

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tim<=32'd0; f_cur<=F_START; load<=1'b0; fcw<=32'd0; en_prev<=1'b0;
        end
        else begin
            load   <= 1'b0;
            en_prev<= en;

            if (en) begin
                if (!en_prev) begin                     // 启动瞬间: 立即到起点
                    tim   <= 32'd0;
                    f_cur <= (F_START + F_STEP > F_END) ? F_START : (F_START + F_STEP);
                    fcw   <= ((F_START * M) >> 24);
                    load  <= 1'b1;
                end
                else if (tim == STEP_CYC - 32'd1) begin // 每 50ms 一步
                    tim   <= 32'd0;
                    f_cur <= f_next;
                    fcw   <= fcw_c;
                    load  <= 1'b1;
                end
                else tim <= tim + 32'd1;
            end
            else begin
                tim   <= 32'd0;
                f_cur <= F_START;
            end
        end
    end
endmodule
