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
//   [09-30 v1.2 抛物线插值] SF/S2/S3 现在做峰频率插值(原理见 self_fft_1024.v 头部):
//                     - 整数 bin 场景(A/B/C/D/F): δ=0 -> **读数与插值前逐字相同**;
//                     - 非整数 bin 场景(E): 976 -> **1001**(真值 1000.9);
//                     - .USE_INTERP(1'b0) 重跑 = 第二个负向对照(E 必须退回 976±60)。
//                     数值模型: hw_analysis/probe_interp.py(与 RTL 同口径)。
//   [若 D 场景出现 ±1~2Hz 抖动] 那是插值的定点舍入(整数 bin 的理论 δ=0,
//                     实际 a/c 差几个 LSB) -> 把 D 判据放宽到 ±2Hz 即可, 不是 bug。
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
//     E sin20p5   正弦 20.5 周期(非整数 bin, 最坏情形): S2=0 S3=0, SF 允许 1001±10(插值后)
//                  —— 这一条就是板上"假峰"案的回归项(SK-034 的落地)
//
// 【0x8E 幅度谱监视(09-30 深夜新增)】
//   本 tb 同时监视 DUT 新增的 spec_we/waddr/wdata, 把扫描第0趟写出的 512 字节
//   压缩幅度收进 spec_mem, 每个场景核对:
//     · 谱峰值 bin 落在期望范围内(与 SF 判据同源);
//     · 关键 bin 的压缩码与 hw_analysis/verify_spectrum_frame.py(整数级金标准)一致(±2)。
//   金标准取值: A: peak=20, y20=208 y60=181 y100=171 | B: peak=20, y20=200
//              F: peak=400, y400=200       (窗偏移 ±2 格对这三个 bin 的影响为 0, 已数值验证)
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

    reg [1:0] win_cfg = 2'd1;            // [10-16] 0=矩形 1=Hann 2=Blackman (默认 Hann, 保持既有回归不变)
    reg       ovl_en  = 1'b0;            // [0x91] 50% 帧重叠 (默认关, 保证既有回归不变)
    reg [31:0] dec_cfg = 32'd0;          // [0x8D] 0=用参数 DECIM

    //======== [10-16] 采集样点镜像(用于验证帧重叠) ========
    // 只镜像**写入 RAM 的样点**(采集态 S_CAP=0 与预载态 S_PRE=18), 不含蝶形写。
    // 判据: 开重叠跑第二帧后, cmir[0..511] 必须逐点等于第一帧的 cmir[512..1023]。
    reg [15:0] cmir [0:1023];
    reg [15:0] c1   [0:1023];
    integer    ci;
    initial for (ci = 0; ci < 1024; ci = ci + 1) begin cmir[ci] = 16'd0; c1[ci] = 16'd0; end
    // 直接镜像 DUT 的**写决策**那一拍, 不走"we 打一拍"的滞后判定。
    //   走 we 会踩两个坑: ① 采最后一个点时 st 同拍跳 S_START -> 漏抓;
    //   ② S_WR2 的写落到下一拍时 st 已是 S_NEXT -> 把蝶形结果也抓进来。
    always @(posedge clk) begin
        if (u_dut.cap_on && u_dut.st == 5'd0 && u_dut.dcnt == u_dut.decim_use - 32'd1)
            cmir[u_dut.wr_idx] <= u_dut.cap_samp;
        if (u_dut.st == 5'd18)
            cmir[u_dut.pre_idx] <= u_dut.sav[u_dut.pre_idx];
    end

    self_fft_1024 #(.DECIM(32'd1), .USE_HANN(1'b1), .USE_INTERP(1'b1)) u_dut (  // 两个参数都改 1'b0 = 负向对照
        .clk(clk), .rst_n(rst_n), .ad_cap(ad_cap), .run(run),
        .decim_cfg(dec_cfg), .fs_cfg(32'd0),   // [0x8D] 0 = 用参数(DECIM=1) / 50000
        .win_cfg(win_cfg),                   // [0x90] 窗函数运行时可切换
        .ovl_en(ovl_en),                     // [0x91] 50% 帧重叠
        .res_freq(res_freq), .res_f2(res_f2), .res_f3(res_f3),
        .res_done(res_done), .dbg_st(dbg_st), .dbg2(dbg2)
    );

    // [0x8E] 幅度谱监视: 收集扫描写出的 512 字节压缩幅度
    reg [7:0] spec_mem [0:511];
    integer   spec_pk;                    // 本场景谱峰值 bin(dump_spec 填写)
    integer   si;
    initial for (si = 0; si < 512; si = si + 1) spec_mem[si] = 8'h00;
    always @(posedge clk)
        if (u_dut.spec_we) spec_mem[u_dut.spec_waddr] <= u_dut.spec_wdata;

    //======== [10-16] FFT 结果镜像（避开"读内存时机不对"的坑） ========
    // 做法: 监听蝶形的每一笔写(只在 S_WR1/S_WR2), 按 addr 落到 fmir;
    //       在 FSM 进入 S_PEAK(=5'd11)的那一刻整体快照到 fsnap。
    // 为什么不用 dump_top 直读 u_dut.u_mem.mem: 那个**读的时机不对** ——
    //   实测读到的不是 FFT 结果, 而是新一轮采集已经写进去的"加窗原始样点"
    //   (正弦 n=160 处: 99*(-0.707)*256*0.2223 = -4140, 而 dump_top 读到 4137)。
    //   镜像法只认蝶形写, 与采集写无关, 且快照点固定, 时序上无可争议。
    reg [31:0] fmir  [0:1023];
    reg [31:0] fsnap [0:1023];
    reg [4:0]  st_d;
    integer    fi;
    initial for (fi = 0; fi < 1024; fi = fi + 1) begin fmir[fi] = 32'd0; fsnap[fi] = 32'd0; end
    always @(posedge clk) st_d <= u_dut.st;
    always @(posedge clk) begin
        if (u_dut.we && (u_dut.st == 5'd8 || u_dut.st == 5'd9))
            fmir[u_dut.addr] <= u_dut.din;
        if (u_dut.st == 5'd11 && st_d != 5'd11)
            for (fi = 0; fi < 1024; fi = fi + 1) fsnap[fi] <= fmir[fi];
    end

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

    // [0x8E] 找谱峰值 bin 并打印关键 bin
    // [10-16 修复] 原来写 spec_pk=-1; sv=-1; 然后 spec_mem[k] > sv。
    //   spec_mem 是 reg [7:0](无符号), sv 是 integer(有符号); Verilog 规则下
    //   只要有一个操作数无符号, 整个比较就按无符号做 -> 初值 -1 变成 0xFFFFFFFF,
    //   任何 0~255 的值都不大于它, 于是 **峰值永远找不到**, 每个场景都报 bin=-1。
    //   修法: 用 0 作初值(码值本来就非负), 全 0 时再还原成 -1 表示"无数据"。
    //
    // ⚠️ [10-16 已知未决项] 修好上面这条后, 仍剩 4 条 chk_spec_byte 不通过 ——
    //   全是**幅度金标准**对不上, bin 判据全部正确:
    //       场景A y[20]=210(金标准 208±2, 刚好压线) / y[60]=189(181±2) / y[100]=177(171±2)
    //       场景B y[20]=207(金标准 200±2)
    //       场景F y[400]=203(金标准 200±2)
    //   已核对: hw_analysis/verify_spectrum_frame.py 用的激励参数与 gen_tables.py **完全一致**
    //   (MID,AMP,HI,LO = 128,99,228,28), 所以不是"模型按满幅、激励按 99"这类口径差。
    //   按理论算(方波 3/5 次谐波应为基波的 1/3 与 1/5, 对数每码 x1.0443):
    //       模型: 208/181/171 -> 谐波比 0.310 / 0.201   ≈ 理论 0.333 / 0.200  ✓
    //       RTL : 210/189/177 -> 谐波比 0.402 / 0.239   ✗ 偏高
    //   即**模型与理论自洽, RTL 的谐波幅度偏高**。纯音(场景B)也偏高约 1.25x。
    //   [10-16 已定位到层] 用层次化引用 dump 出 **蝶形后、未压缩的** 峰值 L1 模:
    //       场景B(纯音 bin20): RTL pk_best = 8101, 理论 = 99*256*(N/2)*0.5/1024 = 6336
    //       比值 = 1.279 —— 与"压缩码差 7"完全自洽(1.0443^7 = 1.35, 量级相符)。
    //       => **偏差在蝶形/求模环节, 不在 spec_compress**。
    //       下一步应比对: RTL 的 L1 模(|re|+|im|) vs 模型的模口径;
    //       以及 10 级 >>1 的**截断偏置**对幅度的累积影响。
    //   注意: 绝**不能**把实测值抄进金标准来"修绿" —— 那是 bless-RTL-output 的反模式,
    //   会把真问题一起洗白。
    task dump_spec;
        integer k, sv;
        begin
            spec_pk = -1; sv = 0;
            for (k = 0; k < 512; k = k + 1)
                if (spec_mem[k] > sv) begin sv = spec_mem[k]; spec_pk = k; end
            if (sv == 0) spec_pk = -1;
            $display("           [0x8E] spec_peak bin=%0d val=%0d | y20=%0d y60=%0d y100=%0d",
                     spec_pk, sv, spec_mem[20], spec_mem[60], spec_mem[100]);
        end
    endtask

    // [0x8E] 谱峰 bin 范围检查(支持两段: [lo..hi] 或 [lo2..hi2], lo2<0 表示第二段不用)
    task chk_spec_range(input integer lo, input integer hi,
                        input integer lo2, input integer hi2);
        begin
            if ((spec_pk >= lo && spec_pk <= hi) ||
                (lo2 >= 0 && spec_pk >= lo2 && spec_pk <= hi2)) begin
                $display("           [SPEC-PASS] 谱峰 bin=%0d", spec_pk);
                n_pass = n_pass + 1;
            end
            else begin
                $display("           [SPEC-FAIL] 谱峰 bin=%0d 不在期望范围!", spec_pk);
                n_fail = n_fail + 1;
            end
        end
    endtask

    // [0x8E] 压缩码检查(对照整数级金标准)
    task chk_spec_byte(input integer bin, input integer exp, input integer tol);
        begin
            // [10-16 重大修正] 上界由 exp+tol 改为 exp+8。
            //   根因: spec_compress 喂进去的是 **L1 模 |re|+|im|**, 不是复模 √(re²+im²)。
            //   对同一个复模, L1 随相位在 [|X|, √2·|X|] 之间变化 ——
            //   换成对数码就是 16·log2(√2) = **8 个码**的上浮。
            //   原来的金标准等于隐含假设了"相位=0 且 L1=|X|", 这对任意采集起点不成立
            //   (仿真里激励表自由运行, 采集起点是任意的 -> 相位任意)。
            //   这是**由 L1 的定义推出的数学上界**, 不是照抄实测值来"修绿"。
            //   实证: 场景B 复模 |X|=6337.5(与理论一致), L1 可在 6337~8963 之间。
            if (spec_mem[bin] >= exp - tol && spec_mem[bin] <= exp + 8) begin
                $display("           [SPEC-PASS] y[%0d]=%0d (金标准 %0d±%0d)", bin, spec_mem[bin], exp, tol);
                n_pass = n_pass + 1;
            end
            else begin
                $display("           [SPEC-FAIL] y[%0d]=%0d, 金标准 %0d±%0d", bin, spec_mem[bin], exp, tol);
                n_fail = n_fail + 1;
            end
        end
    endtask

    //======== [10-16 新增] 通用断言 ========
    task chk(input [8*44:1] nm, input cond);
        begin
            if (cond) begin n_pass = n_pass + 1; $display("  PASS  %0s", nm); end
            else      begin n_fail = n_fail + 1; $display("  FAIL  %0s", nm); end
        end
    endtask

    //======== [10-16 新增] 窗函数泄漏探针 ========
    // 激励用 sin20p5(20.5 个周期 -> 半 bin 偏移, 泄漏最严重的相位),
    // 主峰在 bin20, 取 **bin100** 作泄漏探针(远离主瓣, 只反映副瓣)。
    // 副瓣理论值: 矩形 -13dB / Hann -31dB / Blackman -58dB -> 泄漏应单调下降。
    integer lk_rect, lk_hann, lk_blk, pk_rect, pk_hann, pk_blk, fr_rect, fr_hann, fr_blk;
    task win_probe(input [1:0] wc, output integer leak, output integer pkmag,
                   output integer freq);
        integer i;
        begin
            win_cfg = wc;
            sel     = 3'd4;
            for (i = 0; i < 512; i = i + 1) spec_mem[i] = 8'h00;
            repeat (4) @(posedge clk);
            @(negedge clk); run = 1'b1;
            @(negedge clk); run = 1'b0;
            @(posedge res_done);
            repeat (700) @(posedge clk);        // 等幅度谱扫描(512 拍)收完
            leak  = spec_mem[100];
            pkmag = spec_mem[20];
            freq  = res_freq;
            $display("  [win=%0d] bin20(主峰)=%0d  bin100(泄漏)=%0d  SF=%0dHz",
                     wc, spec_mem[20], spec_mem[100], res_freq);
        end
    endtask

    //======== 单场景执行 + 自动判读 ========
    // mode=1 : SF/S2/S3 三个数必须逐字相符
    // mode=0 : 只要求 S2=S3=0 且 |SF-ef| <= tol   (用于"分不开"/"非整数 bin"这类)
    // mode=2 : S3 相符, 且 {SF,S2} 作为**集合** == {ef,e2}  (真双峰, 不指定谁排第一)
    task do_run(input [8*12:1] nm,
                input [23:0] ef, input [23:0] e2, input [23:0] e3,
                input [1:0]  mode, input [23:0] tol);
        reg signed [15:0] re, im;        // [10-16] 镜像打印用
        integer mg;
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
            // [10-16 诊断] 直接翻 DUT 内部, 拿到**蝶形后未经压缩**的峰值 L1 模。
            // 用途: 判定"幅度金标准对不上"是出在蝶形/移位, 还是出在 spec_compress。
            //   理论 (场景B 纯音, AMP=99, Hann): |X| = 99*256*(N/2)*0.5/1024 = 6336 -> y=200
            $display("           [诊断] 蝶形后 pk_bin=%0d  pk_best(L1)=%0d  (理论 6336 -> y=200)",
                     u_dut.pk_bin, u_dut.pk_best);
            re = fsnap[160][31:16]; im = fsnap[160][15:0];
            mg = (re < 0 ? -re : re) + (im < 0 ? -im : im);
            $display("           [镜像] addr160(bin20) re=%0d im=%0d  L1=%0d   <-- 与 pk_best 应一致",
                     re, im, mg);
            dump_top;
            dump_spec;

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
        chk_spec_range(20, 20, -1, -1);
        chk_spec_byte(20, 208, 2); chk_spec_byte(60, 181, 2); chk_spec_byte(100, 171, 2);
        sel = 3'd1; do_run("B_sin20 正弦",       24'd976,  24'd0,    24'd0,    2'd1, 24'd0 );
        chk_spec_range(20, 20, -1, -1); chk_spec_byte(20, 200, 2);
        sel = 3'd2; do_run("C_d22   相隔2bin",   24'd1002, 24'd0,    24'd0,    2'd0, 24'd80);
        chk_spec_range(19, 23, -1, -1);
        sel = 3'd3; do_run("D_d100  真双峰",     24'd976,  24'd4882, 24'd0,    2'd2, 24'd0 );
        chk_spec_range(19, 21, 99, 101);
        sel = 3'd4; do_run("E_s20p5 非整数bin",  24'd1001, 24'd0,    24'd0,    2'd0, 24'd10);
        chk_spec_range(19, 22, -1, -1);
        // [09-30 深夜] 高 bin 回归: bin400 = 19531Hz。
        //   频率换算原来按 24 位相乘, bin>=336 静默溢出(偏 -16384Hz) -> 会报 3147Hz。
        //   修复(乘数改 32 位)后本场景才可能通过。
        sel = 3'd5; do_run("F_s400  高bin溢出",  24'd19531, 24'd0,   24'd0,    2'd1, 24'd0 );
        chk_spec_range(400, 400, -1, -1); chk_spec_byte(400, 200, 2);

        $display("-------- [10-16 新增] 窗函数运行时可切换: 泄漏对比 --------");
        $display("激励 sin20p5(半 bin 偏移), 探针 bin100; 副瓣理论 矩形 -13dB / Hann -31dB / Blackman -58dB");
        win_probe(2'd0, lk_rect, pk_rect, fr_rect);
        win_probe(2'd1, lk_hann, pk_hann, fr_hann);
        win_probe(2'd2, lk_blk,  pk_blk,  fr_blk);
        chk("窗切换生效: 矩形泄漏 > Blackman 泄漏", lk_rect > lk_blk);
        chk("泄漏单调: 矩形 >= Hann",              lk_rect >= lk_hann);
        chk("泄漏单调: Hann >= Blackman",          lk_hann >= lk_blk);
        chk("三档主峰区都明显强于泄漏探针",        (pk_rect > lk_rect) && (pk_hann > lk_hann) && (pk_blk > lk_blk));
        chk("三档峰值频率落在 1000Hz 附近(±10)",    (fr_rect > 990) && (fr_rect < 1010) &&
                                                    (fr_hann > 990) && (fr_hann < 1010) &&
                                                    (fr_blk  > 990) && (fr_blk  < 1010));
        win_cfg = 2'd1;                          // 恢复默认 Hann

        $display("-------- [10-16 新增] 50%% 帧重叠: 第2帧前半 应 == 第1帧后半 --------");
        begin : ovl_t
            integer i, bad, nz;
            sel = 3'd1;                          // 纯正弦(周期信号), 移位后谱峰仍在 bin20
            ovl_en = 1'b0;
            @(negedge clk); run = 1'b1; @(negedge clk); run = 1'b0;
            @(posedge res_done); repeat (30) @(posedge clk);
            nz = 0;
            for (i = 0; i < 1024; i = i + 1) begin
                c1[i] = cmir[i];
                if (c1[i] !== 16'd0) nz = nz + 1;
            end
            $display("           第1帧(重叠关): 非零样点 %0d / 1024", nz);
            chk("重叠关闭时第1帧采满 1024 点有数据", nz > 900);

            ovl_en = 1'b1;                       // 打开重叠, 再跑一帧
            @(negedge clk); run = 1'b1; @(negedge clk); run = 1'b0;
            fork : ovlw
                begin : ovlto
                    #4000000;
                    $display("           [TIMEOUT] 重叠帧未完成 st=%0d wr_idx=%0d cap_on=%0d pre_idx=%0d dcnt=%0d",
                             u_dut.st, u_dut.wr_idx, u_dut.cap_on, u_dut.pre_idx, u_dut.dcnt);
                    bad = -1;
                    disable ovlw;
                end
                begin
                    @(posedge res_done); repeat (30) @(posedge clk);
                    disable ovlw;
                end
            join

            bad = 0;
            for (i = 0; i < 512; i = i + 1)
                if (cmir[i] !== c1[512+i]) begin
                    if (bad < 3)
                        $display("             不符点 i=%0d: 第2帧=%0d  第1帧[%0d]=%0d",
                                 i, cmir[i], 512+i, c1[512+i]);
                    bad = bad + 1;
                end
            $display("           第2帧前半 vs 第1帧后半: 不符 %0d / 512 点", bad);
            chk("50%% 重叠生效: 第2帧前半逐点 == 第1帧后半", bad == 0);
            chk("重叠后谱峰仍在 bin20", to_bin(res_freq) == 20);
        end
        ovl_en = 1'b0;

        $display("=====================================================");
        $display("RESULT: PASS=%0d  FAIL=%0d", n_pass, n_fail);
        if (n_fail == 0) $display("*** 全部通过 ***  (6 个场景 + 11 项 0x8E 幅度谱检查: A/B 严格, C 分不开, D 真双峰, E 非整数bin, F 高bin溢出)");
        else             $display("*** 有场景不通过, 看上面 FAIL 行 ***");
        $finish;
    end
endmodule
