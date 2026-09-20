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
    assign dbg_st = st;
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
            res_freq<=0; res_done<=0; pk_addr<=0; pk_best<=0; pk_bin<=0;
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
                    din  <= {ad_cap, 24'd0};
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
                    // [09-19] 正半轴+前三峰级联(调试)
                    if (rev10(pk_addr) <= 10'd511) begin
                        if (d_mag > pk_best) begin
                            m2<=pk_best; b2<=pk_bin;
                            m3<=m2;      b3<=b2;
                            pk_best <= d_mag; pk_bin <= rev10(pk_addr);
                        end
                        else if (d_mag > m2) begin
                            m3<=m2; b3<=b2;
                            m2<=d_mag; b2<=rev10(pk_addr);
                        end
                        else if (d_mag > m3) begin
                            m3<=d_mag; b3<=rev10(pk_addr);
                        end
                    end
                    if (pk_addr==10'd1023) st<=S_DONE;
                    else begin pk_addr<=pk_addr+10'd1; st<=S_PEAK; end
                 end
                end
                S_DONE: begin
                    res_freq <= (pk_bin*24'd50000)>>10;
                    res_f2   <= (b2*24'd50000)>>10;       // 第二峰
                    res_f3   <= (b3*24'd50000)>>10;       // 第三峰
                    res_done <= 1'b1;                     // 单拍完成脉冲
                    st<=S_CAP; cap_on<=1'b0; wr_idx<=0; dcnt<=0;   // 回静默, 等下一条 0x8A
                end
                default: st<=S_CAP;
            endcase
        end
    end
endmodule
