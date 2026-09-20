//===========================================================================
// 模块名   : freq_meter v4.0
// 测频     : 自动双模式(10ms闸门 / 32周期测周法), 100Hz~1MHz <1% (不变)
// 占空比   : 测量窗口内 "高电平时钟数 / 窗口时钟数" (对毛刺免疫)
// 脉宽     : 窗口内"最长连续高电平"时钟数 / 50 -> us (对毛刺免疫)
// 判高     : ad_cap > 中线, 且连续 2 拍确认(去毛刺)
// 作者     : WaveCore 队长 | 日期: 2026-09-16 | 版本: v4.0
//===========================================================================

module freq_meter #(
    parameter GATE1_CLKS   = 500_000,
    parameter HYST_L       = 8'd112,
    parameter HYST_H       = 8'd144,
    parameter FINE_CYC     = 6'd32,
    parameter [31:0] FINE_NUM = 32'd1_600_000_000
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    output reg  [23:0] freq_hz,
    output reg  [7:0]  vpp,
    output reg  [15:0] duty_x10,
    output reg  [19:0] width_us,
    output reg         meas_done,
    output reg         meas_done2,
    output wire [2:0]  dbg_st,
    output wire [31:0] dbg_h_tick,
    output wire [31:0] dbg_p_tick
);
    assign dbg_st     = st;
    assign dbg_h_tick = hi_lat;    // 诊断: 高电平计数
    assign dbg_p_tick = r_lat;     // 诊断: 最长连续高电平

    // ============ 状态 ============
    reg [2:0] st;
    localparam ST_COARSE = 3'd0;
    localparam ST_FINE   = 3'd1;
    localparam ST_CALC   = 3'd2;
    localparam ST_D1     = 3'd3;   // 算占空比(减法循环)
    localparam ST_D2     = 3'd4;   // 算脉宽(减法循环)

    // ============ [09-17] 5点中值滤波: 抑制宽至2拍的尖刺 ============
    // 9 比较器排序网络, Python 20万组随机验证 (hw_analysis/med5_net.txt)
    reg  [7:0] ad_p1, ad_p2, ad_p3, ad_p4;
    wire [7:0] a0 = ad_cap, a1 = ad_p1, a2 = ad_p2, a3 = ad_p3, a4 = ad_p4;
    wire [7:0] c0_lo = (a0 < a1) ? a0 : a1;
    wire [7:0] c0_hi = (a0 < a1) ? a1 : a0;
    wire [7:0] c1_lo = (a3 < a4) ? a3 : a4;
    wire [7:0] c1_hi = (a3 < a4) ? a4 : a3;
    wire [7:0] c2_lo = (a2 < c1_hi) ? a2 : c1_hi;
    wire [7:0] c2_hi = (a2 < c1_hi) ? c1_hi : a2;
    wire [7:0] c3_lo = (c2_lo < c1_lo) ? c2_lo : c1_lo;
    wire [7:0] c3_hi = (c2_lo < c1_lo) ? c1_lo : c2_lo;
    wire [7:0] c4_lo = (c0_lo < c3_hi) ? c0_lo : c3_hi;
    wire [7:0] c4_hi = (c0_lo < c3_hi) ? c3_hi : c0_lo;
    wire [7:0] c5_lo = (c4_lo < c3_lo) ? c4_lo : c3_lo;
    wire [7:0] c5_hi = (c4_lo < c3_lo) ? c3_lo : c4_lo;
    wire [7:0] c6_lo = (c0_hi < c2_hi) ? c0_hi : c2_hi;
    wire [7:0] c6_hi = (c0_hi < c2_hi) ? c2_hi : c0_hi;
    wire [7:0] c7_lo = (c6_lo < c4_hi) ? c6_lo : c4_hi;
    wire [7:0] c7_hi = (c6_lo < c4_hi) ? c4_hi : c6_lo;
    wire [7:0] c8_lo = (c7_lo < c5_hi) ? c7_lo : c5_hi;
    wire [7:0] c8_hi = (c7_lo < c5_hi) ? c5_hi : c7_lo;
    // [09-17 时序修复] 中值输出打一拍: 断裂 ad_cap->9级比较器->阈值/计数 长链
    reg  [7:0] ad_med_r;
    // 组合中值 = c8_hi(组合由 p1..p4 生成), 下拍使用

    // ============ 迟滞过零(测频用, 保持不变) ============
    reg        armed;
    reg [7:0]  thr_l;
    reg [7:0]  thr_h;
    wire [8:0] mid_sum = {1'b0, max_v} + {1'b0, min_v};
    wire [7:0] mid_c   = mid_sum[8:1];
    reg [7:0]  vpp_last;
    wire [7:0] db_half = vpp_last[7:4];
    wire [3:0] db_cur  = (db_half > 4'd12) ? 4'd12 :
                         (db_half < 4'd4)  ? 4'd4  : db_half[3:0];
    wire [7:0] next_l = (mid_c > db_cur) ? (mid_c - db_cur) : 8'd0;
    wire [7:0] next_h = (mid_c > (8'd255 - db_cur)) ? 8'd255 : (mid_c + db_cur);
    // [09-17 抗噪] 阈值穿越需"连续2拍"确认: 单点毛刺不再触发过零
    reg  hi_prev_q;
    reg  lo_prev_q;
    wire hi_now_q = (ad_med_r >= thr_h);
    wire lo_now_q = (ad_med_r <= thr_l);
    wire hi2_ok   = hi_now_q && hi_prev_q;    // 连续2拍高
    wire lo2_ok   = lo_now_q && lo_prev_q;    // 连续2拍低(重新武装也要2拍)
    wire upcross  = armed && hi2_ok;

    // ============ 占空比/脉宽: 计窗统计法 ============
    // [09-17] 判高改为施密特迟滞: 高于 mid+db 置位, 低于 mid-db 清零
    //         带内的小毛刺/振铃不再把高电平时段"切碎"
    reg        hi_flag;
    wire       hi_set  = (ad_med_r >= next_h);
    wire       hi_clr  = (ad_med_r <= next_l);
    wire       hi_now  = (ad_med_r > mid_c);       // (保留观察用)
    reg        hi_prev;
    wire       hi_ok   = hi_flag;                // 统计用判高
    reg [31:0] win_cnt;      // 窗口时钟数
    reg [31:0] high_cnt;     // 高电平时钟数
    reg [31:0] run_cnt;      // 当前连续高电平长度
    reg [31:0] max_run;      // 最长连续高电平
    reg [31:0] hi_lat, r_lat;   // 本帧锁存
    reg [31:0] win_lat;         // 本帧窗口长度

    // ============ 粗测/细测 ============
    reg [18:0] gate_cnt;
    reg [16:0] cnt_gate;
    reg [5:0]  ev_cnt;
    reg [24:0] t_cnt;
    reg        div_start;
    wire       div_done;
    wire [31:0] div_q;
    reg        t_ok;
    reg [12:0] wd_cnt;
    reg [31:0] div_num;
    reg [24:0] div_den;
    div_restore #(.N(32), .D(25)) u_div (
        .clk(clk), .rst_n(rst_n), .start(div_start),
        .num(div_num), .den(div_den), .q(div_q), .done(div_done)
    );

    reg [7:0] max_v, min_v;
    wire [23:0] clamp_val = (div_q > 24'd9_999_999) ? 24'd9_999_999 : div_q[23:0];

    // 减法循环用
    reg [31:0] loop_a;      // 被除数(逐次减)
    reg [31:0] loop_b;      // 除数
    reg [15:0] loop_q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= ST_COARSE; armed <= 1'b1;
            thr_l <= 8'd112; thr_h <= 8'd144;
            gate_cnt <= 19'd0; cnt_gate <= 17'd0;
            ev_cnt <= 6'd0; t_cnt <= 25'd0;
            div_start <= 1'b0; t_ok <= 1'b0; wd_cnt <= 13'd0;
            div_num <= 32'd0; div_den <= 25'd0;
            max_v <= 8'd0; min_v <= 8'd255; vpp_last <= 8'd255;
            freq_hz <= 24'd0; vpp <= 8'd0;
            meas_done <= 1'b0; meas_done2 <= 1'b0;
            hi_prev <= 1'b0; hi_prev_q <= 1'b0; lo_prev_q <= 1'b0;
            hi_flag <= 1'b0;
            ad_p1 <= 8'd128; ad_p2 <= 8'd128; ad_p3 <= 8'd128; ad_p4 <= 8'd128;
            ad_med_r <= 8'd128;
            win_cnt <= 32'd0; high_cnt <= 32'd0;
            run_cnt <= 32'd0; max_run <= 32'd0;
            hi_lat <= 32'd0; r_lat <= 32'd0; win_lat <= 32'd0;
            duty_x10 <= 16'd0; width_us <= 20'd0;
            loop_a <= 32'd0; loop_b <= 32'd0; loop_q <= 16'd0;
        end
        else begin
            div_start  <= 1'b0;
            meas_done  <= 1'b0;
            meas_done2 <= 1'b0;

            // ---- 中值滤波移位(5抽头) ----
            ad_p1 <= ad_cap;
            ad_p2 <= ad_p1;
            ad_p3 <= ad_p2;
            ad_p4 <= ad_p3;
            ad_med_r <= c8_hi;                 // 中值打拍
            // ---- 数据统计(每个时钟都跑) ----
            if (hi_set)      hi_flag <= 1'b1;
            else if (hi_clr) hi_flag <= 1'b0;
            hi_prev <= hi_now;
            hi_prev_q <= hi_now_q;
            lo_prev_q <= lo_now_q;
            win_cnt <= win_cnt + 32'd1;
            if (hi_ok) begin
                high_cnt <= high_cnt + 32'd1;
                run_cnt  <= run_cnt + 32'd1;
            end
            else begin
                run_cnt <= 32'd0;
                if (run_cnt > max_run) max_run <= run_cnt;
            end

            // ---- 测频用迟滞 ----
            if (upcross) armed <= 1'b0;
            else if (lo2_ok) armed <= 1'b1;
            if (ad_med_r > max_v) max_v <= ad_med_r;
            if (ad_med_r < min_v) min_v <= ad_med_r;

            case (st)
                ST_COARSE: begin
                    if (gate_cnt == GATE1_CLKS - 1) begin
                        if (cnt_gate >= 17'd100) begin
                            freq_hz  <= (cnt_gate * 17'd100 > 24'd9_999_999) ?
                                        24'd9_999_999 : (cnt_gate * 17'd100);
                            vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                            vpp_last <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                            meas_done <= 1'b1;
                            // 锁存统计 + 清窗
                            hi_lat <= high_cnt; r_lat <= max_run; win_lat <= win_cnt;
                            win_cnt <= 32'd0; high_cnt <= 32'd0;
                            run_cnt <= 32'd0; max_run <= 32'd0;
                            gate_cnt <= 19'd0; cnt_gate <= 17'd0;
                            thr_l <= next_l; thr_h <= next_h;
                            max_v <= 8'd0; min_v <= 8'd255;
                            wd_cnt <= 13'd0;
                            st <= ST_D1;
                        end
                        else begin
                            // 低频: 重开统计窗(丢弃粗测期数据), 只统计细测 32 周期
                            st <= ST_FINE; gate_cnt <= 19'd0; cnt_gate <= 17'd0;
                            ev_cnt <= 6'd0; t_cnt <= 25'd0;
                            win_cnt <= 32'd0; high_cnt <= 32'd0;
                            run_cnt <= 32'd0; max_run <= 32'd0;
                            max_v <= 8'd0; min_v <= 8'd255;
                        end
                    end
                    else begin
                        gate_cnt <= gate_cnt + 19'd1;
                        if (upcross && cnt_gate < 17'h1FFFF)
                            cnt_gate <= cnt_gate + 17'd1;
                    end
                end

                ST_FINE: begin
                    if (upcross) begin
                        if (ev_cnt == FINE_CYC - 1) begin
                            if ((t_cnt >= 24'd2) && (t_cnt < 25'h1_000000)) begin
                                t_ok <= 1'b1;
                                div_num <= FINE_NUM; div_den <= t_cnt[24:0];
                                div_start <= 1'b1; wd_cnt <= 13'd0;
                                st <= ST_CALC;
                            end
                            else begin
                                freq_hz  <= 24'd0;
                                vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                                vpp_last <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                                meas_done <= 1'b1;
                                hi_lat <= high_cnt; r_lat <= max_run; win_lat <= win_cnt;
                                win_cnt <= 32'd0; high_cnt <= 32'd0;
                                run_cnt <= 32'd0; max_run <= 32'd0;
                                thr_l <= next_l; thr_h <= next_h;
                                max_v <= 8'd0; min_v <= 8'd255;
                                ev_cnt <= 6'd0; t_cnt <= 25'd0;
                                wd_cnt <= 13'd0; st <= ST_D1;
                            end
                        end
                        else ev_cnt <= ev_cnt + 6'd1;
                    end
                    if (t_cnt < 24'hFFFFFF) t_cnt <= t_cnt + 25'd1;
                    if (t_cnt == 24'hFFFFFF) begin
                        freq_hz <= 24'd0;
                        vpp     <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        vpp_last<= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        meas_done <= 1'b1;
                        hi_lat <= high_cnt; r_lat <= max_run; win_lat <= win_cnt;
                        win_cnt <= 32'd0; high_cnt <= 32'd0;
                        run_cnt <= 32'd0; max_run <= 32'd0;
                        thr_l <= next_l; thr_h <= next_h;
                        max_v <= 8'd0; min_v <= 8'd255;
                        ev_cnt <= 6'd0; t_cnt <= 25'd0;
                        wd_cnt <= 13'd0; st <= ST_D1;
                    end
                end

                ST_CALC: begin
                    wd_cnt <= wd_cnt + 13'd1;
                    if (div_done || wd_cnt == 13'd4095) begin
                        freq_hz <= div_done ? (t_ok ? clamp_val : 24'd0) : 24'd0;
                        vpp     <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        vpp_last<= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        meas_done <= 1'b1;
                        hi_lat <= high_cnt; r_lat <= max_run; win_lat <= win_cnt;
                        win_cnt <= 32'd0; high_cnt <= 32'd0;
                        run_cnt <= 32'd0; max_run <= 32'd0;
                        thr_l <= next_l; thr_h <= next_h;
                        max_v <= 8'd0; min_v <= 8'd255;
                        wd_cnt <= 13'd0; st <= ST_D1;
                    end
                end

                ST_D1: begin
                    // duty_x10 = hi_lat * 1000 / win_lat (减法循环, <=1001 拍)
                    if (wd_cnt == 13'd0) begin
                        // duty = hi/win; 先各右移6位再算, 防 hi*1000 溢出
                        loop_a <= (hi_lat >> 6) * 32'd1000;
                        loop_b <= ((win_lat >> 6) != 0) ? (win_lat >> 6) : 32'd1;
                        loop_q <= 16'd0;
                        wd_cnt <= 13'd1;
                    end
                    else begin
                        wd_cnt <= wd_cnt + 13'd1;
                        if (loop_a < loop_b || wd_cnt == 13'd4095) begin
                            duty_x10 <= loop_q;
                            wd_cnt   <= 13'd0;
                            st       <= ST_D2;
                        end
                        else begin
                            loop_a <= loop_a - loop_b;
                            loop_q <= loop_q + 16'd1;
                        end
                    end
                end

                ST_D2: begin
                    // width_us = r_lat / 50 (减法循环, 上限保护)
                    if (wd_cnt == 13'd0) begin
                        loop_a <= (r_lat > 32'd5_000_000) ? 32'd5_000_000 : r_lat;
                        loop_q <= 16'd0;
                        wd_cnt <= 13'd1;
                    end
                    else begin
                        wd_cnt <= wd_cnt + 13'd1;
                        if (loop_a < 32'd50 || wd_cnt == 13'd4095) begin
                            width_us   <= (r_lat > 32'd5_000_000) ? 20'd99_999 : loop_q;
                            meas_done2 <= 1'b1;
                            wd_cnt     <= 13'd0;
                            st         <= ST_COARSE;
                        end
                        else begin
                            loop_a <= loop_a - 32'd50;
                            loop_q <= loop_q + 16'd1;
                        end
                    end
                end
                default: st <= ST_COARSE;
            endcase
        end
    end


endmodule
