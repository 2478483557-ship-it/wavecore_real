//===========================================================================
// 模块名   : self_fft_1024  (自研 1024 点 Radix-2 DIF FFT, F4 对比用)
// 算法     : 原地 DIF, 输入自然序, 输出位反转; 每级 >>1 (总增益 1/1024)
// 调度     : 与 hw_analysis 金标准逐拍一致 (已验证: 1kHz → bin20)
// 存储     : blk_mem_gen_1 (1024 x 32 单口, 无输出寄存器, 读延迟1拍)
// 运行     : 自动循环: 采1024点(50kHz) -> 10级蝶形 -> 找峰 -> 输出一次
// 作者     : WaveCore 队长 | 2026-09-16 | v1.1
//===========================================================================
module self_fft_1024 #(
    parameter DECIM = 32'd1000
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    input  wire        run,          // 0x8A: 运行一次(脉冲); 平时静默
    output reg  [23:0] res_freq,     // 峰值频率(Hz) = bin*50000/1024
    output reg  [23:0] res_f2,       // [调试] 第二峰
    output reg  [23:0] res_f3,       // [调试] 第三峰
    output reg         res_done,     // 一次完成脉冲
    output wire [3:0]  dbg_st,       // [调试] 当前状态(0~13)
    output wire [3:0]  dbg2          // [调试] {cap_on, wr_idx[9:7]}
);
    // [09-27 修复] 原此处有一句重复的 "assign dbg_st = st;" 位于 reg 声明之前,
    // 会把 st 隐式声明成 1 位 wire(Vivado 综合放过, 但 XSim 直接报
    // VRFC 10-3380 "identifier 'st' is used before its declaration")。已删, 只保留下方声明后的那一句。
    //======== 存储(单口) ========
    reg  [9:0]  addr;
    reg  [31:0] din;
    reg         we;
    wire [31:0] dout;
    blk_mem_gen_1 u_mem (
        .clka (clk), .addra(addr), .dina(din), .wea(we), .douta(dout)
    );

    //======== 旋转因子 ROM ========
    reg  [9:0]  tw_addr;
    wire [15:0] tw_c, tw_s;
    twiddle_rom u_tw (.clk(clk), .addr(tw_addr), .cos_o(tw_c), .sin_o(tw_s));

    //======== 采集 ========
    reg [31:0] dcnt;
    reg [9:0]  wr_idx;
    reg        cap_on;
    reg        run_l;                 // run 脉冲锁存
    reg        done_latch;            // [调试] 完成锁存(once done, stays)
    reg [16:0] done_hold;             // [调试] DONE 停驻计数(约2ms), 供轨迹采样
    reg w1_go, w2_go;                 // [09-19 修复] 读延迟自适应等待(覆盖1/2拍延迟)
    reg pk_go;                        // [09-19 修复] 找峰同样等一拍(2拍延迟)
    assign dbg2 = {done_latch, cap_on, wr_idx[9:8]};

    //======== FSM ========
    reg [3:0] st;
    assign dbg_st = st;
    localparam S_CAP  = 4'd0,
               S_START= 4'd1,
               S_RD1  = 4'd2,
               S_W1   = 4'd3,
               S_RD2  = 4'd4,
               S_W2   = 4'd5,
               S_MUL  = 4'd6,
               S_MUL2 = 4'd7,
               S_MUL3 = 4'd14,
               S_WR1  = 4'd8,
               S_WR2  = 4'd9,
               S_NEXT = 4'd10,
               S_PEAK = 4'd11,
               S_PKRD = 4'd12,
               S_DONE = 4'd13;

    reg [3:0]  stage;
    reg [9:0]  base, j, half, nblk, blk, i1, i2;

    reg signed [15:0] ar, ai, br, bi;
    reg signed [15:0] cr, ci;

    reg [9:0]  pk_addr;
    reg [16:0] pk_best;
    reg [9:0]  pk_bin;
    reg [16:0] m2,m3;                 // [调试] 第2/3峰幅度
    reg [9:0]  b2,b3;                 // [调试] 第2/3峰bin
    // [调试] 采集体检计数
    reg [10:0]  cnt_wr;               // 写入点数
    reg [23:0]  cnt_cy;               // 采集持续拍数
    reg [10:0]  lat_wr;               // 锁存: 点数
    reg [23:0]  lat_cy;               // 锁存: 拍数

    // 位反转
    function [9:0] rev10(input [9:0] v);
        integer k;
        begin
            for (k=0;k<10;k=k+1) rev10[k] = v[9-k];
        end
    endfunction

    //======== [09-27 修复] 峰值判据: 最小间隔 + 幅度门限 ========
    // 问题: 原实现是"幅度前三大"级联, 同一主瓣的相邻 bin(如 976Hz/1025Hz = bin20/21)
    //       会被当成"第二峰", 对外说成"三峰"有答辩风险。
    // 修复: 三趟扫描 0=全局最大 1=第二峰 2=第三峰, 第 2/3 峰必须与已选峰相隔 >= GAP bin;
    //       再叠加"幅度 >= 主峰/8"门限(与 IP 通路 A 行判据一致), 低于门限报 0 = 无有效峰。
    //
    //======== [09-30 上板修复] GAP 4 -> 6: 本通路未加窗, GAP=4 会漏出假峰 ========
    // 现象: 上板跑 1kHz 正弦(非整数 bin)时读出 S2=0001171Hz, 而仿真永远是 0。
    // 根因: 本通路是**矩形窗**(没加窗; Hann 窗只在 IP 通路 fft_demo.v 里)。
    //   1kHz @ fs=50kHz/N=1024 -> 1000/48.828 = bin 20.480, **非整数**。
    //   矩形窗的 Dirichlet 核在 bin24(离主峰 4 bin)处 = 主峰 x 13.6%,
    //   而幅度门限是主峰/8 = 12.5% -> 13.6% 刚好越线 -> 报成"第二峰"。
    //   最坏相位(小数=0.5)时可达 14.3%, 所以假峰是"时有时无"(约 65% 的频率会中)。
    // 为什么仿真抓不到: sim/fft_check 的激励是"1024 点正好 k 个整周期",
    //   谱线精确落在整数 bin, 矩形窗泄漏在该处恰好为 0 -> 假峰永远不出现。
    //   ★ 又一次"仿真通过 != 硬件正确", 激励必须覆盖**非整数 bin** 的情况。
    // 修法: GAP 4 -> 6。第一个合格 bin 移到 bin26, 泄漏降到 8.7%(最坏相位 9.1%),
    //   稳定低于 12.5% 门限。对真实谱峰无影响 —— 1kHz 方波的 3/5 次谐波在 bin61/bin102,
    //   离基波 41/82 bin, 远大于 6; 双音 80bin 同样不受影响。
    // 备选(未采用, 见 report/ 待办): 复用 hann_1024.hex 给本通路也加 Hann 窗 —
    //   那是根因修复, 但会改变输出幅度、需完整回归, 故本期先用最小改动。
    localparam [9:0] GAP = 10'd6;      // [09-30] 原为 10'd4; 矩形窗需 >=6 bin 才压住泄漏
    reg  [1:0] scan;                   // 当前第几趟
    wire [9:0] cur_bin = rev10(pk_addr);
    wire [9:0] d_pk = (cur_bin > pk_bin) ? (cur_bin - pk_bin) : (pk_bin - cur_bin);
    wire [9:0] d_b2 = (cur_bin > b2)     ? (cur_bin - b2)     : (b2 - cur_bin);
    wire       far_pk  = (d_pk >= GAP);
    wire       far_all = (d_pk >= GAP) && (d_b2 >= GAP);

    // ---- 蝶形组合运算 ----
    wire signed [16:0] sumr = ar + br;        // 17位
    wire signed [16:0] sumi = ai + bi;
    wire signed [16:0] difr = ar - br;
    wire signed [16:0] difi = ai - bi;
    wire signed [15:0] o1r = sumr >>> 1;      // 除2(防溢出)
    wire signed [15:0] o1i = sumi >>> 1;
    // [09-17 时序修复] 乘法先打拍(消除 mult->sub->shift 长链)
    reg  signed [31:0] p_rr, p_ii, p_ri, p_ir;
    wire signed [15:0] o2r = (p_rr - p_ii) >>> 16; // 打拍后仅剩 sub+shift(短)
    wire signed [15:0] o2i = (p_ri + p_ir) >>> 16;

    // ---- 峰值功率(有符号平方, 33位) ----
    // [09-17 时序修复] 找峰用 L1 范数(|re|+|im|): 免乘法, 单调性足够找峰
    wire signed [15:0] d_re = dout[31:16];
    wire signed [15:0] d_im = dout[15:0];
    wire [16:0] d_mag = (d_re[15] ? (~d_re + 1) : d_re) + (d_im[15] ? (~d_im + 1) : d_im);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st<=S_CAP; dcnt<=0; wr_idx<=0; cap_on<=1'b0; run_l<=1'b0; done_latch<=1'b0;
            done_hold<=17'd0; w1_go<=1'b0; w2_go<=1'b0;
            cnt_wr<=11'd0; cnt_cy<=24'd0; lat_wr<=11'd0; lat_cy<=24'd0;
            pk_go<=1'b0;
            addr<=0; din<=0; we<=0; tw_addr<=0;
            stage<=0; base<=0; j<=0; half<=10'd512; nblk<=10'd1; blk<=0; i1<=0; i2<=0;
            ar<=0;ai<=0;br<=0;bi<=0;cr<=0;ci<=0;
            p_rr<=0;p_ii<=0;p_ri<=0;p_ir<=0;
            res_freq<=0; res_done<=0; pk_addr<=0; pk_best<=0; pk_bin<=0; scan<=2'd0;
        end
        else begin
            we <= 1'b0;
            res_done <= 1'b0;
            if (run) begin run_l <= 1'b1; done_latch <= 1'b0; end  // 新任务清锁存

            // ---- 采集(仅收到 run 后进行一次) ----
            if (!cap_on && run_l && st==S_CAP) begin
                cap_on <= 1'b1;
                run_l  <= 1'b0;
                dcnt   <= 32'd0;
                wr_idx <= 10'd0;
                cnt_wr <= 11'd0;      // [调试] 清体检计数
                cnt_cy <= 24'd0;
            end
            else if (cap_on && st==S_CAP) begin
                cnt_cy <= cnt_cy + 24'd1;   // [调试] 采集拍数
                    if (dcnt==DECIM-1) begin
                        dcnt <= 0;
                        addr <= wr_idx; we <= 1'b1;
                        // [09-28 修复·重要] ADC 是"偏移二进制"(中点 128), 而蝶形与找峰
                        // 全程按"有符号补码"解释 dout[31:16]。原来的 {ad_cap,24'd0} 相当于
                        // 把 ad_cap 当"有符号 8 位"用: ad_cap>=128 会变成负数,
                        // 于是在 128 处出现一个"断崖", 正弦(29~227)被劈成锯齿,
                        // 凭空造出 3 次/5 次谐波 -> S2/S3 全是假的;
                        // 而且 ad_cap=128 会映到 -32768(满量程负), 直流分量巨大。
                        // 修法: 异或 0x80 = 减 128(mod 256), 得到真正的中点归零补码。
                        //   128 -> 0x00 ->    0      (中点归零)
                        //   228 -> 0x64 -> +25600    (原 228-128=+100)
                        //    28 -> 0x9C -> -25600    (原  28-128=-100)
                        // 对照: IP 通路 fft_demo.v 一直是 $signed({8'd0,m_q})-128, 本来就是对的。
                        din  <= {(ad_cap ^ 8'h80), 24'd0};
                        cnt_wr <= cnt_wr + 11'd1;    // [调试] 点数
                    if (wr_idx==10'd1023) begin
                        wr_idx<=0; cap_on<=1'b0; st<=S_START;
                        lat_wr <= cnt_wr + 11'd1;   // [调试] 锁存(含本拍)
                        lat_cy <= cnt_cy + 24'd1;
                    end
                    else wr_idx <= wr_idx + 10'd1;
                end
                else dcnt <= dcnt + 32'd1;
            end

            case (st)
                S_CAP: ;    // [09-19 修复] 空项: 防 default 吞掉"采集结束->S_START"的赋值
                S_START: begin
                    stage<=0; base<=0; blk<=0; j<=0;
                    half<=10'd512; nblk<=10'd1;
                    st<=S_RD1;
                end
                S_RD1: begin i1<=base+j; addr<=base+j; w1_go<=1'b0; st<=S_W1; end
                S_W1:  begin
                             if (!w1_go) w1_go<=1'b1;          // 多等一拍: 兼容 2 拍读延迟
                             else begin
                                 ar<=dout[31:16]; ai<=dout[15:0];
                                 i2<=(base+j)+half; st<=S_RD2;
                             end
                         end
                S_RD2: begin addr<=i2; w2_go<=1'b0; st<=S_W2; end
                S_W2:  begin
                             if (!w2_go) w2_go<=1'b1;          // 多等一拍
                             else begin
                                 br<=dout[31:16]; bi<=dout[15:0];
                                 tw_addr<=j<<stage[3:0]; st<=S_MUL;
                             end
                         end
                S_MUL: begin st<=S_MUL2; end
                S_MUL2:begin cr<=tw_c; ci<=tw_s; st<=S_MUL3; end
                S_MUL3:begin                                  // 乘法打拍
                             p_rr <= difr * cr;
                             p_ii <= difi * ci;
                             p_ri <= difr * ci;
                             p_ir <= difi * cr;
                             st   <= S_WR1;
                         end
                S_WR1: begin addr<=i1; din<={o1r,o1i}; we<=1'b1; st<=S_WR2; end
                S_WR2: begin addr<=i2; din<={o2r,o2i}; we<=1'b1; st<=S_NEXT; end
                S_NEXT: begin
                    if (j+1 < half) begin
                        j  <= j + 10'd1;
                        st <= S_RD1;                    // 修: 推进后回读下一只蝴蝶
                    end
                    else begin
                        j <= 0;
                        if (blk+1 < nblk) begin
                            blk  <= blk + 10'd1;
                            base <= base + (half<<1);
                            st   <= S_RD1;              // 修: 换块后回读
                        end
                        else begin
                            blk <= 0; base <= 0;
                            if (stage==4'd9) begin
                                pk_addr<=0; pk_best<=0; pk_bin<=0; m2<=0; m3<=0; b2<=0; b3<=0;
                                scan<=2'd0;
                                st<=S_PEAK;
                            end
                            else begin
                                stage<=stage+4'd1;
                                half<=half>>1;
                                nblk<=nblk<<1;
                                st<=S_RD1;
                            end
                        end
                    end
                end
                S_PEAK: begin addr<=pk_addr; pk_go<=1'b0; st<=S_PKRD; end
                S_PKRD: begin
                 if (!pk_go) pk_go<=1'b1;                  // 等一拍(2拍读延迟)
                 else begin
                    // [09-27] 三趟扫描: 0=全局最大, 1=第二峰(离主峰>=GAP), 2=第三峰(离前两峰>=GAP)
                    // [09-28] 排除 bin0(直流): 直流不是"频率分量"。修复输入映射后直流≈0,
                    //        这一条只是兜底, 防止残余直流把 SF 顶成 0Hz。
                    if (cur_bin >= 10'd1 && cur_bin <= 10'd511) begin   // 只看正半轴, 跳过直流
                        case (scan)
                            2'd0: if (d_mag > pk_best) begin
                                      pk_best <= d_mag; pk_bin <= cur_bin;
                                  end
                            2'd1: if (far_pk && (d_mag > m2)) begin
                                      m2 <= d_mag; b2 <= cur_bin;
                                  end
                            default: if (far_all && (d_mag > m3)) begin
                                      m3 <= d_mag; b3 <= cur_bin;
                                  end
                        endcase
                    end
                    if (pk_addr==10'd1023) begin
                        if (scan != 2'd2) begin                // 还有下一趟: 重头再扫
                            scan    <= scan + 2'd1;
                            pk_addr <= 10'd0;
                            st      <= S_PEAK;
                        end
                        else st<=S_DONE;
                    end
                    else begin pk_addr<=pk_addr+10'd1; st<=S_PEAK; end
                 end
                end
                S_DONE: begin
                    res_freq <= (pk_bin*24'd50000)>>10;
                    // [09-27] 门限: 幅度 >= 主峰/8 才认(与 IP 通路 A 行判据一致); 否则报 0 = 无有效峰
                    res_f2   <= (m2 >= (pk_best>>3)) ? ((b2*24'd50000)>>10) : 24'd0;
                    res_f3   <= (m3 >= (pk_best>>3)) ? ((b3*24'd50000)>>10) : 24'd0;
                    res_done <= 1'b1;                     // 单拍完成脉冲
                    st<=S_CAP; cap_on<=1'b0; wr_idx<=0; dcnt<=0;   // 回静默, 等下一条 0x8A
                end
                default: st<=S_CAP;
            endcase
        end
    end
endmodule
