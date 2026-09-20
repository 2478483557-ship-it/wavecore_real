//===========================================================================
// 模块名   : wave_id v1.1 (波形自动识别 —— 修正版)
// 原理     : 50kHz 降采样流(每1000拍取1点) 上做两阶段统计(各2048点≈41ms):
//            阶段0: 跟踪 min/max -> span/mid; 阶段1: 统计 |x-mid| > 3/8*span 占比
//            占比 >0.84 方波 / 0.40~0.62 正弦 / 0.18~0.38 三角 / 其他
// 输入     : ad_cap(与测量同一采集流, 50MHz域)
// 输出     : wave_type: 0=方波 1=正弦 2=三角 3=其他
// 作者     : WaveCore 队长 | 日期: 2026-09-20 | v1.1 修正采样率(关键!)
//===========================================================================
module wave_id (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ad_cap,
    output reg  [1:0] wave_type
);
    // ---- 50kHz 降采样节拍 ----
    reg  [9:0] dcnt;
    wire tick = (dcnt == 10'd999);

    // ---- 采样级 3点中值(对降采样点) ----
    reg  [7:0] s0, a1, a2;       // 当前采样点 + 两级历史(均为降采样点)
    wire [7:0] med = ( (s0<a1) ? ((a1<a2)?a1:((s0<a2)?a2:s0))
                               : ((s0<a2)?s0:((a1<a2)?a2:a1)) );

    // ---- 统计状态 ----
    reg  [1:0]  ph;              // 0=测幅 1=计数
    reg  [10:0] cnt;             // 0..2047 (降采样点计数)
    reg  [7:0]  mn, mx, mid, span;
    reg  [11:0] hi_cnt;
    wire [7:0]  th3 = (span >> 2) + (span >> 3);     // 3/8*span
    wire [8:0]  abs_d = (med > mid) ? (med - mid) : (mid - med);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dcnt<=10'd0; s0<=8'd128; a1<=8'd128; a2<=8'd128;
            ph<=2'd0; cnt<=11'd0; mn<=8'hFF; mx<=8'h00;
            mid<=8'h80; span<=8'h00; hi_cnt<=12'd0; wave_type<=2'd3;
        end
        else begin
            // 节拍发生器
            if (tick) dcnt <= 10'd0;
            else      dcnt <= dcnt + 10'd1;

            if (tick) begin
                s0 <= ad_cap;        // 新样本进入中值链
                a2 <= a1;
                a1 <= s0;            // 注: 流水一节, 无碍统计

                cnt <= (cnt == 11'd2047) ? 11'd0 : (cnt + 11'd1);

                if (cnt == 11'd2047) begin
                    if (ph == 2'd0) begin
                        mid  <= (mn + mx) >> 1;
                        span <= mx - mn;
                        ph   <= 2'd1;
                        hi_cnt <= 12'd0;
                    end
                    else begin
                        if (span < 8'd16)                       wave_type <= 2'd3;
                        else if (hi_cnt > 12'd1720)             wave_type <= 2'd0;
                        else if (hi_cnt >= 12'd819 &&
                                 hi_cnt <= 12'd1270)            wave_type <= 2'd1;
                        else if (hi_cnt >= 12'd369 &&
                                 hi_cnt <= 12'd778)             wave_type <= 2'd2;
                        else                                    wave_type <= 2'd3;
                        ph <= 2'd0;
                        mn <= 8'hFF; mx <= 8'h00;
                    end
                end
                else begin
                    if (ph == 2'd0) begin
                        if (s0 > mx) mx <= s0;
                        if (s0 < mn) mn <= s0;
                    end
                    else begin
                        if (abs_d > th3) hi_cnt <= hi_cnt + 12'd1;
                    end
                end
            end
        end
    end
endmodule
