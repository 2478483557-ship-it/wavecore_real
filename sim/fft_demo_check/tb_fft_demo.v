//===========================================================================
// 测试台 : tb_fft_demo —— fft_demo 改动前后"等价性"回归
// 目的   : 2026-09-30 把 f_ram 从 32768 个触发器改成真块 RAM(见 fft_demo v3.3),
//          必须证明: 灌给 xfft 的样点流**逐字节没变**。
// 做法   : 用 xfft_stub 替身收样点并打滚动校验和; 对 fft_demo 的新旧两版各跑
//          一遍, 比对 [STUB] 行。校验和一致 = 数据通路等价。
// 激励   : ad_cap 用 8 位 LFSR 伪随机(每个时钟都变), DECIM=4 抽点
//          —— 任何一处读地址差一拍, 4096 个抽点全会变, 校验和立刻炸。
// 作者   : WaveCore 队长 | 日期: 2026-09-30
//===========================================================================
`timescale 1ns/1ps

module tb_fft_demo;

    reg  clk   = 1'b0;
    reg  rst_n = 1'b0;
    reg  [7:0] ad_r;

    wire [23:0] fft_hz_w, fft_hz2_w;
    wire        fft_done_w, fft_done2_w;

    always #5 clk = ~clk;                      // 100 MHz

    // ---- 8 位 LFSR: 每个样点都不一样, 对地址偏移最敏感 ----
    initial ad_r = 8'h01;
    always @(posedge clk)
        if (rst_n) ad_r <= {ad_r[6:0], ad_r[7] ^ ad_r[5] ^ ad_r[4] ^ ad_r[3]};

    fft_demo #(.DECIM(32'd4), .NFFT(16'd4096)) dut (
        .clk      (clk        ),
        .rst_n    (rst_n      ),
        .ad_cap   (ad_r       ),
        .fft_hz   (fft_hz_w   ),
        .fft_hz2  (fft_hz2_w  ),
        .fft_done (fft_done_w ),
        .fft_done2(fft_done2_w)
    );

    // ---- 观测找峰输出(替身固定在第 5 根谱线给幅度 -> 期望 61 Hz) ----
    always @(posedge clk)
        if (fft_done_w)
            $display("[TB] fft_done: fft_hz=%0d (expect 61)", fft_hz_w);

    initial begin
        #100 rst_n = 1'b1;
        #800000;
        $display("[TB] finished");
        $finish;
    end

endmodule
