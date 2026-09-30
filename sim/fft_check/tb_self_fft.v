//===========================================================================
// tb_self_fft : 自研 FFT 三峰判据 + 输入映射 回归仿真
//---------------------------------------------------------------------------
// 被验对象 : src/self_fft_1024.v
//
// 【为什么要验】答辩风险清单上的两条:
//   风险1 输入映射: 原来把 ADC 的"偏移二进制"(中点 128) 直接塞进 32 位字
//                   再按有符号读回, 等价于把 ad_cap 当"有符号 8 位"用。
//                   后果 A: ad_cap=128 映到 -32768, 直流分量巨大;
//                   后果 B: ad_cap 跨过 128 时符号翻转, 正弦被劈成锯齿,
//                          凭空造出 3 次/5 次谐波 —— 于是"双音/S2/S3"全是假的。
//                   实测证据(修复前): 方波与正弦跑出**逐字相同**的 976/2929/4882。
//   风险2 假峰: 老的"幅度前三大"会把同一主瓣里的相邻 bin 当第二、第三峰。
//                   改法 = 三趟扫描 + 最小间隔 GAP bin + 幅度门限 主峰/8。
//   [2026-09-30 傍晚更新] 上板又抓到一个"结构性假峰"(1kHz 正弦报 S2=1171=bin24):
//                   根因是本通路**只有矩形窗**, 而 1kHz 落在非整数 bin 20.480。
//                   当天两步走: ① GAP 4->6 先把症状压住; ② 本通路也加 **Hann 窗**
//                   (根因修复, 泄漏 14.7%->0.9%)。对应到本测试平台:
//                   - 新增场景 E(非整数 bin, sin20p5), 把板上的 bug 变成永久回归项;
//                   - 场景 C/D 的期望值按"加窗后"重算(见下面每条后面的话);
//                   - .USE_HANN(1'b1) 显式写出, 改成 1'b0 重跑 = 负向对照
//                     (此时场景 E 必须报 S2=1171, 否则说明这个测试根本抓不到那个 bug)。
//
//   [时序细节·已用数据排除] tb 用 DECIM=1(一拍一个样点), 而 hann_rom 的输出是**寄存器**,
//                   且 RTL 里 `w_addr <= wr_idx` 是每拍都赋 -> DECIM=1 时窗系数整体
//                   **落后 2 格**(实际生效 w[(n-2) mod 1024])。数值模型验证: 对整数 bin 的
//                   纯音, 窗的循环移位只贡献一个线性相位, |X(k)| **完全不变**,
//                   4 个场景读数逐字相同 -> 所以 tb 保持 DECIM=1 是对的, 不必动。
//                   (板上 DECIM=1000, 两次采样隔 1000 拍, 窗系数与样点严格对齐。)
//
// 【期望值怎么来的】表里放"正好整数个周期"的激励 -> 谱线正好落在第 k 根 bin,
//   无泄漏, 期望值是纯算术推出来的, 不靠肉眼。
//     A sq20      方波 ±100, 20 周期: SF= 976(bin20) S2=2929(bin60) S3=4882(bin100)
//                  —— 方波 3/5 次谐波幅度 1/3、1/5(-9.5/-14dB), 高于 -18dB 门限, 该报
//     B sin20     正弦,      20 周期: SF= 976        S2=   0        S3=   0
//                  —— 真正的单峰。修复前这里是 976/2929/4882, 就是上面那个 bug 的证据
//     C dual20_22 双音(相距 2 bin): S2=0 S3=0, SF 允许 1002±80(976/1024/1074 都可能)
//                  —— 2 bin < 主瓣 4 bin, 物理上分不开, 报单峰才是诚实
//                  [加窗后修正] Hann 把主瓣加宽, bin20/21/22 幅度只差 0.1%,
//                  峰值 bin 由取整噪声决定 -> 判据不能钉死在 1002±60
//     D dual20_100 双音(相距 80 bin): {SF,S2} = {976,4882}(bin20 与 bin100), S3=0
//                  —— 证明 GAP 约束没把"真双峰"也一起干掉
//                  [加窗后修正] 两音**等幅**, 谁排第一本来就是并列的(模型只差 0.09%),
//                  改窗后次序会翻 -> 判据改成"集合相等", 不指定谁当 SF
//     E sin20p5   正弦 20.5 周期(非整数 bin, 最坏情形): S2=0 S3=0, SF 允许 976±60
//                  —— 这一条就是板上"假峰"案的回归项(SK-034 的落地)
//
// 说明 1: DECIM=1(一拍一个样点)。板上是 DECIM=1000=50kHz, DECIM 只决定"采满
//         1024 点要多久", 不参与 FFT 数学, 取 1 让仿真快 1000 倍。
// 说明 2: 激励用整数查表, 不用 $sin —— XSim 2020.2 对 $sin/real 支持不稳定
//         (实测全 0), 会把结论带偏。
// 用法   : bash run_fft_check.sh
// 作者   : WaveCore 队长 | 2026-09-28
//===========================================================================
`timescale 1ns / 1ps

module tb_self_fft;
    reg         clk    = 1'b0;
    reg         rst_n  = 1'b0;
    reg  [7:0]  ad_cap = 8'd128;
    reg         run    = 1'b0;
    wire [23:0] res_freq, res_f2, res_f3;
    wire        res_done;
    wire [3:0]  dbg_st, dbg2;

    integer n_pass = 0, n_fail = 0;

    always #10 clk = ~clk;                       // 20ns 周期 = 50MHz

    self_fft_1024 #(.DECIM(32'd1), .USE_HANN(1'b1)) u_dut (   // 改 1'b0 = 负向对照
        .clk(clk), .rst_n(rst_n), .ad_cap(ad_cap), .run(run),
        .res_freq(res_freq), .res_f2(res_f2), .res_f3(res_f3),
        .res_done(res_done), .dbg_st(dbg_st), .dbg2(dbg2)
    );

    //======== 激励: 1024 点查表, 每拍推进一格(与 DUT 采样严格同拍) ========
    reg [9:0] ridx = 10'd0;
    reg [2:0] sel  = 3'd0;                       // 0=sq 1=sin 2=dual22 3=dual100 4=sin20p5 5=sin400(高bin)

    always @(posedge clk) ridx <= ridx + 10'd1;

    reg [7:0] rom_sq   [0:1023];
    reg [7:0] rom_sin  [0:1023];
    reg [7:0] rom_d22  [0:1023];
    reg [7:0] rom_d100 [0:1023];
    reg [7:0] rom_s205 [0:1023];
    reg [7:0] rom_s400 [0:1023];                 // [09-30] 高 bin 溢出回归
    initial begin
        $readmemh("sq20.hex",       rom_sq  );
        $readmemh("sin20.hex",      rom_sin );
        $readmemh("dual20_22.hex",  rom_d22 );
        $readmemh("dual20_100.hex", rom_d100);
        $readmemh("sin20p5.hex",    rom_s205);
        $readmemh("sin400.hex",     rom_s400);
    end

    always @* begin
        case (sel)
            3'd0:    ad_cap = rom_sq  [ridx];
            3'd1:    ad_cap = rom_sin [ridx];
            3'd2:    ad_cap = rom_d22 [ridx];
            3'd3:    ad_cap = rom_d100[ridx];
            3'd4:    ad_cap = rom_s205[ridx];     // 非整数 bin
            default: ad_cap = rom_s400[ridx];     // 3'd5: 高 bin(400) -> 溢出回归
        endcase
    end

    // res_freq(Hz) 反推 bin: bin = round(res*1024/50000)
    function integer to_bin(input [23:0] f);
        begin to_bin = (f * 1024 + 25000) / 50000; end
    endfunction

    // [诊断] 确认四张表真的不一样
    task dump_tab;
        begin
            $display("  [rom] sq=%0d/%0d sin=%0d/%0d d22=%0d/%0d d100=%0d/%0d s205=%0d/%0d s400=%0d/%0d (第0/1点)",
                rom_sq[0],rom_sq[1], rom_sin[0],rom_sin[1],
                rom_d22[0],rom_d22[1], rom_d100[0],rom_d100[1],
                rom_s205[0],rom_s205[1], rom_s400[0],rom_s400[1]);
        end
    endtask

    // [诊断] 直接翻 DUT 内部 RAM 里 FFT 写完的频谱, 打印前 6 大谱线
    //        注意: 自研 FFT 输出是"位反转"存放, 所以下面打印的是**存储地址**
    //        地址 -> 真实 bin 要过 rev10: 例如地址 160 -> bin 20, 地址 223 -> bin 1004
    task dump_top;
        integer k, i, j, mg, nf;
        reg signed [15:0] re, im;
        integer bi [0:5];
        integer bm [0:5];
        integer tmp;
        begin
            for (i = 0; i < 6; i = i + 1) begin bi[i] = -1; bm[i] = -1; end
            for (k = 0; k < 512; k = k + 1) begin
                re = u_dut.u_mem.mem[k][31:16];
                im = u_dut.u_mem.mem[k][15:0];
                mg = (re < 0 ? -re : re) + (im < 0 ? -im : im);
                nf = 0;
                for (i = 0; i < 6 && nf == 0; i = i + 1) begin
                    if (mg > bm[i]) begin
                        for (j = 5; j > i; j = j - 1) begin
                            bm[j] = bm[j-1]; bi[j] = bi[j-1];
                        end
                        bm[i] = mg; bi[i] = k;
                        nf = 1;
                    end
                end
            end
            $write("           [top6 @addr]");
            for (i = 0; i < 6; i = i + 1) $write("  a%0d=%0d", bi[i], bm[i]);
            $write("\n");
        end
    endtask

    //======== 单场景执行 + 自动判读 ========
    // mode=1 : SF/S2/S3 三个数必须逐字相符
    // mode=0 : 只要求 S2=S3=0 且 |SF-ef| <= tol   (用于"分不开"/"非整数 bin"这类)
    // mode=2 : S3 相符, 且 {SF,S2} 作为**集合** == {ef,e2}  (真双峰, 不指定谁排第一)
    task do_run(input [8*12:1] nm,
                input [23:0] ef, input [23:0] e2, input [23:0] e3,
                input [1:0]  mode, input [23:0] tol);
        begin
            $display("----------------------------------------------");
            $display("[%0s] 期望 SF=%0d S2=%0d S3=%0d (mode=%0d)",
                     nm, ef, e2, e3, mode);

            @(negedge clk);  run = 1'b1;         // 避开时钟沿, 保证被采到
            @(negedge clk);  run = 1'b0;

            fork : w
                begin : to
                    #10000000;               // 10ms(50 万拍) 超时
                    $display("[TIMEOUT] %0s  st=%0d dbg2=%b ridx=%0d",
                             nm, dbg_st, dbg2, ridx);
                    n_fail = n_fail + 1;
                end
                begin
                    @(posedge res_done);
                    disable w;
                end
            join

            $display("           实测 SF=%0d(bin%0d) S2=%0d(bin%0d) S3=%0d(bin%0d)",
                     res_freq, to_bin(res_freq),
                     res_f2,   to_bin(res_f2),
                     res_f3,   to_bin(res_f3));
            dump_top;

            if (mode == 2'd1) begin               // 严格: 三个数逐字相符
                if (res_freq === ef && res_f2 === e2 && res_f3 === e3) begin
                    $display("           >>> PASS");
                    n_pass = n_pass + 1;
                end
                else begin
                    $display("           >>> FAIL");
                    n_fail = n_fail + 1;
                end
            end
            else if (mode == 2'd2) begin          // 集合相等: 真双峰, 不指定谁排第一
                if (res_f3 === e3 &&
                    ((res_freq === ef && res_f2 === e2) ||
                     (res_freq === e2 && res_f2 === ef))) begin
                    $display("           >>> PASS (两峰都报对了, 顺序不计)");
                    n_pass = n_pass + 1;
                end
                else begin
                    $display("           >>> FAIL");
                    n_fail = n_fail + 1;
                end
            end
            else begin                            // 单峰判据: S2=S3=0 且 SF 在容差内
                if (res_f2 === 24'd0 && res_f3 === 24'd0 &&
                    res_freq <= ef + tol && res_freq >= ef - tol) begin
                    $display("           >>> PASS (单峰, 无假峰)");
                    n_pass = n_pass + 1;
                end
                else begin
                    $display("           >>> FAIL");
                    n_fail = n_fail + 1;
                end
            end
            #200;
        end
    endtask

    initial begin
        rst_n = 1'b0;
        sel   = 2'd0;
        repeat (20) @(posedge clk);
        rst_n = 1'b1;
        repeat (5)  @(posedge clk);

        $display("======== self_fft_1024 regression (输入映射 + 三峰判据) ========");
        $display("fs=50kHz N=1024 -> 1 bin=48.83Hz; GAP=6 bin; 自测通路已加 Hann 窗");
        $display("门限: 第 2/3 峰幅度 >= 主峰/8 (-18dB), 否则报 0");
        dump_tab;

        sel = 3'd0; do_run("A_sq20  方波",       24'd976,  24'd2929, 24'd4882, 2'd1, 24'd0 );
        sel = 3'd1; do_run("B_sin20 正弦",       24'd976,  24'd0,    24'd0,    2'd1, 24'd0 );
        sel = 3'd2; do_run("C_d22   相隔2bin",   24'd1002, 24'd0,    24'd0,    2'd0, 24'd80);
        sel = 3'd3; do_run("D_d100  真双峰",     24'd976,  24'd4882, 24'd0,    2'd2, 24'd0 );
        sel = 3'd4; do_run("E_s20p5 非整数bin",  24'd976,  24'd0,    24'd0,    2'd0, 24'd60);
        // [09-30 深夜] 高 bin 回归: bin400 = 19531Hz。
        //   频率换算原来按 24 位相乘, bin>=336 静默溢出(偏 -16384Hz) -> 会报 3147Hz。
        //   修复(乘数改 32 位)后本场景才可能通过。
        sel = 3'd5; do_run("F_s400  高bin溢出",  24'd19531, 24'd0,   24'd0,    2'd1, 24'd0 );

        $display("=====================================================");
        $display("RESULT: PASS=%0d  FAIL=%0d", n_pass, n_fail);
        if (n_fail == 0) $display("*** 全部通过 ***  (6 个场景: A/B 严格, C 分不开, D 真双峰, E 非整数bin, F 高bin溢出)");
        else             $display("*** 有场景不通过, 看上面 FAIL 行 ***");
        $finish;
    end
endmodule
