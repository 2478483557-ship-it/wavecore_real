//===========================================================================
// 模块名   : lockin_core
// 功能     : 数字锁相放大 -- 正交相干解调 + 整周期累加
//
// 原理     : 把 ADC 采样与同频正交参考相乘，再对若干个完整周期求和。
//            与参考同频的信号在 I/Q 上累积成直流，噪声与其它频率被平均掉。
//            累加"整数个周期"是关键：非整数周期会残留 2f 分量，导致读数抖动。
//
// 参考从哪来 : 用 DDS 的同一个频率字 fcw。DDS 跑在 50MHz，本模块的参考 NCO
//            跑在 25MHz（ADC 实际速率），所以频率字取 2xfcw，两者频率严格相等。
//
// 相位约定  : 本模块只保证"同频"，不保证绝对相位对齐（DDS 与 ADC 之间存在
//            固定但未知的延迟）。因此输出的是 I/Q 两个正交分量，
//            幅度 = sqrt(I^2+Q^2) 与相位偏移无关，主机侧计算即可。
//
// 作者     : WaveCore | 2026-10-23
//===========================================================================
`timescale 1ns / 1ps

module lockin_core (
    input  wire               clk,      // 50MHz 系统时钟
    input  wire               rst_n,
    input  wire [7:0]         ad_cap,   // 50MHz 域, 每个样点保持 2 拍
    input  wire [31:0]        fcw,      // DDS 频率字(50MHz 域)
    input  wire               en,       // 使能, 关闭时累加器清零
    input  wire [15:0]        m_per,    // 累加周期数(默认 32)
    output reg  signed [47:0] i_out,    // 同相分量(锁存值)
    output reg  signed [47:0] q_out,    // 正交分量(锁存值)
    output reg  [31:0]        n_out,    // 本块累加的样点数
    output reg                done      // 块结束, 一拍脉冲
);

    // 最多累加 4M 样点(≈168ms @25MHz)。再多也没意义，
    // 而且 48 位累加器会溢出(1 个样点最大 128x32767 ≈ 2^22)
    localparam [31:0] N_MAX = 32'd4_194_304;

    // ---------------- 25MHz 采样节拍 ----------------
    // ad_driver 在 sys_clk 下降沿采，每个样点保持 2 拍；这里隔一拍取一次，
    // 得到与 ADC 实际速率一致的 25MHz 样点流。
    reg sstep;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) sstep <= 1'b0;
        else        sstep <= ~sstep;
    end

    // ---------------- 参考 NCO(25MHz 域) ----------------
    reg  [31:0] phase;
    reg  [9:0]  raddr;
    wire [31:0] fcw2      = {fcw[30:0], 1'b0};              // x2，补偿 50->25MHz
    wire [31:0] phase_nxt = phase + fcw2;
    wire        wrap_nxt  = (phase_nxt < phase);            // 相位溢出 = 走完一个周期

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase <= 32'd0;
            raddr <= 10'd0;
        end else if (en && sstep) begin
            phase <= phase_nxt;
            raddr <= phase_nxt[31:22];                      // 取高 10 位 -> 1024 点表
        end
    end

    // 旋转因子表：与自研 FFT 共用同一份数据(cos / -sin, Q1.15)
    wire [15:0] cos_o, sin_o;
    twiddle_rom u_ref (
        .clk  (clk  ),
        .addr (raddr),
        .cos_o(cos_o),
        .sin_o(sin_o)
    );

    // ---------------- 三级流水：把样点与参考对齐 ----------------
    // ROM 读延迟 1 拍，加上本级的取址与采样，共需 2 拍对齐。
    reg signed [8:0] ad_s0, ad_s1, ad_s2;
    reg              v0, v1, v2;
    reg              w0, w1, w2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ad_s0 <= 9'sd0; ad_s1 <= 9'sd0; ad_s2 <= 9'sd0;
            v0 <= 1'b0; v1 <= 1'b0; v2 <= 1'b0;
            w0 <= 1'b0; w1 <= 1'b0; w2 <= 1'b0;
        end else begin
            v0 <= en && sstep;
            ad_s0 <= $signed({1'b0, ad_cap}) - 9'sd128;     // 去偏置, 转有符号
            w0  <= en && sstep && wrap_nxt;

            v1 <= v0;  ad_s1 <= ad_s0;  w1 <= w0;
            v2 <= v1;  ad_s2 <= ad_s1;  w2 <= w1;
        end
    end

    // ---------------- 相干乘法 ----------------
    // sin_o 存的是 -sin，所以 Q 分量直接乘 sin_o 即可，后面按需统一符号。
    wire signed [24:0] prod_i = ad_s2 * $signed(cos_o);
    wire signed [24:0] prod_q = ad_s2 * $signed(sin_o);

    // ---------------- 整周期累加 ----------------
    reg signed [47:0] iacc, qacc;
    reg        [31:0] nacc;
    reg        [15:0] wcnt;                                 // 已累加的完整周期数

    wire signed [47:0] ia_sum = iacc + {{23{prod_i[24]}}, prod_i};
    wire signed [47:0] qa_sum = qacc + {{23{prod_q[24]}}, prod_q};
    wire        [32:0] n_sum  = {1'b0, nacc} + 33'd1;
    wire        [16:0] w_sum  = {1'b0, wcnt} + {16'd0, w2};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            iacc <= 48'sd0; qacc <= 48'sd0; nacc <= 32'd0; wcnt <= 16'd0;
            i_out <= 48'sd0; q_out <= 48'sd0; n_out <= 32'd0; done <= 1'b0;
        end else begin
            done <= 1'b0;
            if (!en) begin
                // 关闭时清零，重新打开从新的一块开始，避免旧值混进来
                iacc <= 48'sd0; qacc <= 48'sd0; nacc <= 32'd0; wcnt <= 16'd0;
            end else if (v2) begin
                if ((w_sum >= {1'b0, m_per}) || (n_sum >= {1'b0, N_MAX})) begin
                    // 凑够整周期（或到上限）-> 锁存并重新开始
                    i_out <= ia_sum;
                    q_out <= qa_sum;
                    n_out <= n_sum[31:0];
                    done  <= 1'b1;
                    iacc  <= 48'sd0; qacc <= 48'sd0; nacc <= 32'd0; wcnt <= 16'd0;
                end else begin
                    iacc <= ia_sum;
                    qacc <= qa_sum;
                    nacc <= n_sum[31:0];
                    wcnt <= w_sum[15:0];
                end
            end
        end
    end

endmodule
