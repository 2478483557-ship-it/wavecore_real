//===========================================================================
// 模块名   : sig_noise
// 功能     : 给 DDS 输出叠加伪随机噪声，并可衰减信号本身
//
// 为什么需要 : 锁相放大要演示"信号埋在噪声里还能测出来"。板内回环没有外部
//            噪声源，所以用 LFSR 造噪声加在 DAC 输出上；
//            同时要能把信号本身调小，才能让 SNR 掉到 0dB 以下。
//
// 参数     : level  0=关噪声, 1..8 噪声幅度，最大约 +/-127 LSB
//            shift  0=不衰减, 1..4 信号右移(1/2 ~ 1/16)
//
// 实现     : 16 位 LFSR(多项式 x^16+x^14+x^13+x^11+1)，取高 8 位当噪声。
//            噪声与信号都是"以 128 为中心"的偏移量，相加后饱和到 0~255，
//            避免回绕产生刺耳的跳变（回绕会被 ADC 采成大幅毛刺，污染演示）。
//
// 作者     : WaveCore | 2026-10-23
//===========================================================================
`timescale 1ns / 1ps

module sig_noise (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] din,      // DDS 波形(无符号, 128 为中心)
    input  wire [3:0] level,    // 噪声档位 0..8
    input  wire [2:0] shift,    // 信号衰减 0..4
    output reg  [7:0] dout
);

    // ---------------- LFSR 噪声源 ----------------
    reg [15:0] lfsr;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) lfsr <= 16'hACE1;       // 非零初值，否则锁死在全 0
        else        lfsr <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
    end

    wire signed [7:0] rnd    = lfsr[15:8];                       // 当作有符号
    wire        [3:0] nshift = 4'd8 - level;                     // level=8 时不移位
    wire signed [7:0] noise  = (level == 4'd0) ? 8'sd0
                                                : (rnd >>> nshift);
    wire signed [7:0] noise2 = (level > 4'd8) ? 8'sd0 : noise;   // 防御: 档位越界

    // ---------------- 信号衰减 ----------------
    wire signed [8:0] sig0 = $signed({1'b0, din}) - 9'sd128;     // 去中心
    wire signed [8:0] sig1 = (shift > 3'd4) ? 9'sd0 : (sig0 >>> shift);

    // ---------------- 相加并饱和 ----------------
    wire signed [9:0] sum = sig1 + {{2{noise2[7]}}, noise2};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) dout <= 8'd128;
        else if (sum > 10'sd127)  dout <= 8'd255;                // 上饱和
        else if (sum < -10'sd128) dout <= 8'd0;                  // 下饱和
        else                      dout <= sum[7:0] + 8'd128;     // 回中心
    end

endmodule
