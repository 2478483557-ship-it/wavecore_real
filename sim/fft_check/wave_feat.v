//===========================================================================
// 模块名   : wave_feat  (波形识别的 6 个特征提取器)
// 功能     : 吃 1024 个时域样点(补码 8bit), 吐出 6 个 Q15 特征给 wave_nn
// 特征     : 与 hw_analysis/train_wave_nn.py 的 feats() 逐条对齐（94% 那版）
//              pk = max|x|
//              f0 = cnt(x>0)/1024                    -> Q15: cnt*32
//              f1 = |mean(x)|/pk                     -> Q15: |Σx|*32/pk
//              f2 = min(kurt/3, 1), kurt = m4/m2^2   -> Q15: Σx⁴*2^25/(3·(Σx²)²)
//              f3 = min(rms/pk, 1)                   -> Q15: √(Σx²)*1024/pk
//              f4 = min(mean|dx|/pk*2, 1)            -> Q15: Σ|dx|*64/pk
//              f5 = 过零率/1024                       -> Q15: zc*32
// 关键设计 : 只有 pk 需要除 -> 累加器全在 x 域做, 除法留到最后统一做;
//            f2 里的 pk 会自然约掉, 一次 pk 都不用除。
// 资源     : 1 个共用顺序除法器(40/26, 40 拍) + 1 个移位相减开方(32→16, 16 拍)
//            一帧 6 次运算 ≈ 256 拍, 相对一帧 100 万拍可忽略
// 作者     : WaveCore 队长 | 日期: 2026-10-17 | v1.0
//===========================================================================
module wave_feat (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,        // 1 拍脉冲: 开始统计
    input  wire signed [7:0] din,
    input  wire        din_valid,    // 一个有效样点
    output reg  [15:0] f0, f1, f2, f3, f4, f5,   // Q15, 0..32767
    output reg         done,
    output reg  [3:0]  dbg_st,
    output reg  [3:0]  dbg_op
);
    localparam S_IDLE = 4'd0, S_ACC = 4'd1, S_CALC = 4'd2, S_DONE = 4'd3;
    localparam NOP    = 4'd6;        // 共 6 次运算: 索引 0..5

    reg [3:0]  st;
    reg [10:0] cnt;
    reg signed [7:0] prev;
    reg        prev_v;
    reg [8:0]  pk;                    // max|x|: 0..128(9 位, |-128| 溢出 8 位)

    // ---- 累加器(位宽按最坏情况推) ----
    reg [10:0]        a_hi;           // count(x>0)      ≤1024      -> 11
    reg signed [20:0] a_s;            // Σx              |≤|1024*128 -> 21
    reg [26:0]        a_sq;           // Σx²             ≤16.8e6   -> 27
    reg [39:0]        a_x4;           // Σx⁴             ≤2.7e11   -> 40 ← 最宽
    reg [19:0]        a_sl;           // Σ|x[n]-x[n-1]|  ≤1024*255 -> 20
    reg [10:0]        a_zc;           // 过零次数        ≤1024      -> 11

    wire [8:0]  abs8 = din[7] ? (9'd0 - {1'b0, din[7:0]}) : {1'b0, din[7:0]};
    wire [17:0] sq8  = abs8 * abs8;                       // ≤16384 -> 15 位, 留余量
    wire [33:0] x4_8 = sq8 * sq8;                         // ≤2.68e8 -> 28 位, 留余量
    // 相邻差分: din-prev 是**有符号**差, 范围 -255..255, 需 9 位
    wire signed [8:0] dif9 = {din[7], din} - {prev[7], prev};
    wire [8:0]        adif = dif9[8] ? (9'd0 - dif9) : dif9;

    // ---- 共用顺序除法器: 40 位 / 26 位, 40 拍 ----
    reg [39:0] dv_n, dv_r, dv_q, dv_cap;
    reg [25:0] dv_d;
    reg [5:0]  dv_i;
    reg        dv_bsy;
    wire [40:0] dv_sh = {dv_r[38:0], 1'b0};
    wire        dv_ge = (dv_sh[39:0] >= {14'd0, dv_d});

    // ---- 开方: 32 位 -> 16 位, 16 拍 ----
    reg [31:0] sq_x, sq_r;
    reg [15:0] sq_q, sq_b, sq_cap;
    reg [5:0]  sq_i;
    reg        sq_bsy;
    wire [33:0] sq_t  = {sq_r[31:0], 2'b00};
    wire [33:0] sq_bx = {16'd0, sq_b, 2'b01};
    wire        sq_ge = (sq_t >= sq_bx);
    // 减法的低 32 位: 不能写 (a-b)[31:0], Verilog 不允许对表达式位选
    wire [33:0] sq_sub = sq_t - sq_bx;
    wire [31:0] sq_nx  = sq_ge ? sq_sub[31:0] : sq_t[31:0];

    // ---- 运算序号与"已启动"标志 ----
    reg [3:0]  op_idx;
    reg        op_run;
    reg [15:0] r_sqrt;
    reg [21:0] sx_abs;                // |Σx|
    reg [39:0] d4;                    // Σx⁴/Σx²

    wire busy   = dv_bsy | sq_bsy;
    wire dv_end = dv_bsy & (dv_i == 6'd39);

    integer ii;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; cnt <= 11'd0; prev <= 8'sd0; prev_v <= 1'b0; pk <= 9'd0;
            a_hi <= 11'd0; a_s <= 21'sd0; a_sq <= 27'd0;
            a_x4 <= 40'd0; a_sl <= 20'd0; a_zc <= 11'd0;
            f0 <= 16'd0; f1 <= 16'd0; f2 <= 16'd0; f3 <= 16'd0; f4 <= 16'd0; f5 <= 16'd0;
            done <= 1'b0; dbg_st <= 4'd0; dbg_op <= 4'd0;
            dv_n <= 40'd0; dv_r <= 40'd0; dv_q <= 40'd0; dv_d <= 26'd0;
            dv_i <= 6'd0; dv_bsy <= 1'b0; dv_cap <= 40'd0;
            sq_x <= 32'd0; sq_r <= 32'd0; sq_q <= 16'd0; sq_b <= 16'd0;
            sq_i <= 6'd0; sq_bsy <= 1'b0; sq_cap <= 16'd0;
            op_idx <= 4'd0; op_run <= 1'b0; r_sqrt <= 16'd0; sx_abs <= 22'd0; d4 <= 40'd0;
        end
        else begin
            done   <= 1'b0;
            dbg_st <= st;
            dbg_op <= op_idx;

            //======== 除法器推进 ========
            if (dv_bsy) begin
                dv_r <= dv_ge ? (dv_sh[39:0] - {14'd0, dv_d}) : dv_sh[39:0];
                dv_q <= {dv_q[38:0], dv_ge};
                if (dv_i == 6'd39) dv_bsy <= 1'b0;
                else               dv_i   <= dv_i + 6'd1;
            end
            // 最后一步: 商锁存
            if (dv_end) dv_cap <= {dv_q[38:0], dv_ge};

            //======== 开方推进 ========
            if (sq_bsy) begin
                sq_r <= sq_nx;
                sq_q <= sq_ge ? (sq_q | sq_b) : sq_q;
                sq_x <= {sq_x[29:0], 2'b00};
                sq_b <= sq_b >> 1;
                if (sq_i == 6'd15) begin
                    sq_bsy <= 1'b0;
                    sq_cap <= sq_ge ? (sq_q | sq_b) : sq_q;
                end
                else sq_i <= sq_i + 6'd1;
            end

            case (st)
                //======== 统计 1024 个样点 ========
                S_IDLE: begin
                    if (start) begin
                        cnt <= 11'd0; prev_v <= 1'b0; pk <= 9'd0;
                        a_hi <= 11'd0; a_s <= 21'sd0; a_sq <= 27'd0;
                        a_x4 <= 40'd0; a_sl <= 20'd0; a_zc <= 11'd0;
                        op_idx <= 4'd0; op_run <= 1'b0;
                        st <= S_ACC;
                    end
                end
                S_ACC: begin
                    if (din_valid) begin
                        if (abs8 > pk) pk <= abs8;
                        if (din > 8'sd0) a_hi <= a_hi + 11'd1;
                        a_s  <= a_s  + $signed({{13{din[7]}}, din});
                        a_sq <= a_sq + sq8;
                        a_x4 <= a_x4 + x4_8;
                        if (prev_v) begin
                            a_sl <= a_sl + adif;
                            if (din[7] != prev[7]) a_zc <= a_zc + 11'd1;
                        end
                        prev  <= din; prev_v <= 1'b1;
                        if (cnt == 11'd1023) st <= S_CALC;
                        else cnt <= cnt + 11'd1;
                    end
                end
                //======== 串行: 6 个操作, 每个"启动 -> 等完成 -> 存结果" ========
                S_CALC: begin
                    if (!busy) begin
                        if (!op_run) begin
                            // ---- 启动第 op_idx 个操作 ----
                            op_run <= 1'b1;
                            case (op_idx)
                                4'd0: begin   // ① f1 = |Σx|*32 / pk
                                    sx_abs <= a_s[20] ? (~{1'b0, a_s} + 22'd1) : {1'b0, a_s};
                                    dv_n <= {18'd0, sx_abs} << 5;               // 18+22 = 40 位
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd1: begin   // ② f4 = Σ|dx|*64 / pk
                                    dv_n <= {20'd0, a_sl} << 6;
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd2: begin   // ③ 开方 √(Σx²)
                                    sq_x <= {5'd0, a_sq};
                                    sq_r <= 32'd0; sq_q <= 16'd0; sq_b <= 16'h8000;
                                    sq_i <= 6'd0; sq_bsy <= 1'b1;
                                end
                                4'd3: begin   // ④ f3 = √(Σx²)*1024 / pk
                                    dv_n <= {24'd0, sq_cap} << 10;
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd4: begin   // ⑤ d4 = Σx⁴ / Σx²
                                    dv_n <= a_x4;
                                    dv_d <= {1'b0, a_sq[24:0]};                 // 26 位(a_sq≤16.8e6 < 2^25)
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd5: begin   // ⑥ f2 = d4*2^25 / (3·Σx²)
                                    dv_n <= d4 << 25;
                                    dv_d <= (a_sq[24:0] * 3'd3);                // ≤50.4e6 < 2^26
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                default: begin op_run <= 1'b0; st <= S_DONE; end
                            endcase
                        end
                        else begin
                            // ---- 第 op_idx 个操作完成, 存结果 ----
                            op_run  <= 1'b0;
                            op_idx  <= op_idx + 4'd1;
                            case (op_idx)
                                4'd0: f1 <= (dv_cap > 40'd32767) ? 16'd32767 : dv_cap[15:0];
                                4'd1: f4 <= (dv_cap > 40'd32767) ? 16'd32767 : dv_cap[15:0];
                                4'd2: r_sqrt <= sq_cap;      // 开方结果, 下一操作要用
                                4'd3: f3 <= (dv_cap > 40'd32767) ? 16'd32767 : dv_cap[15:0];
                                4'd4: d4 <= dv_cap;
                                4'd5: f2 <= (dv_cap > 40'd32767) ? 16'd32767 : dv_cap[15:0];
                                default: ;
                            endcase
                        end
                    end
                end
                S_DONE: begin
                    // f0/f5 是纯移位, 无需求值循环
                    f0 <= (a_hi >= 11'd1024) ? 16'd32767 : {5'd0, a_hi} << 5;
                    f5 <= (a_zc >= 11'd1024) ? 16'd32767 : {5'd0, a_zc} << 5;
                    done <= 1'b1;
                    st   <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
