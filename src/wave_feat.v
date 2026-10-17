//===========================================================================
// 模块名   : wave_feat  (波形识别的 6 个特征提取器)
// 功能     : 吃 1024 个时域样点(补码 8bit), 吐出 6 个 Q15 特征给 wave_nn
// 特征     : 与 hw_analysis/train_wave_nn.py 的 feats() 逐条对齐（94% 那版）
//              pk = max|x|
//              f0 = cnt(x>0)/1024                    -> Q15: cnt*32
//              f1 = |mean(x)|/pk                     -> Q15: |sumx|*32/pk
//              f2 = min(kurt/3, 1), kurt = m4/m2^2   -> Q15: sumx^4*2^25/(3·(sumx^2)^2)
//              f3 = min(rms/pk, 1)                   -> Q15: √(sumx^2)*1024/pk
//              f4 = min(mean|dx|/pk*2, 1)            -> Q15: sum|dx|*64/pk
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
    reg signed [20:0] a_s;            // sumx              |≤|1024*128 -> 21
    reg [26:0]        a_sq;           // sumx^2             ≤16.8e6   -> 27
    reg [39:0]        a_x4;           // sumx^4             ≤2.7e11   -> 40 ← 最宽
    reg [19:0]        a_sl;           // sum|x[n]-x[n-1]|  ≤1024*255 -> 20
    reg [10:0]        a_zc;           // 过零次数        ≤1024      -> 11

    // [10-17 修复·关键] 取绝对值必须**先符号扩展成 9 位有符号再去负**。
    //   原来写 {1'b0, din[7:0]} 把 -120 当成无符号 136, 9'd0-136 在 9 位下 = 376,
    //   于是 pk 得到 372/376(超出 8 位), 所有特征全错 —— 实测 pk=372 才发现的。
    wire signed [8:0] d9s  = {din[7], din};                    // -128..127
    wire [8:0]  abs8 = d9s[8] ? (9'd0 - d9s) : d9s;            // 0..128
    wire [17:0] sq8  = abs8 * abs8;                       // ≤16384 -> 15 位, 留余量
    wire [33:0] x4_8 = sq8 * sq8;                         // ≤2.68e8 -> 28 位, 留余量
    // 相邻差分: din-prev 是**有符号**差, 范围 -255..255, 需 9 位
    wire signed [8:0] dif9 = {din[7], din} - {prev[7], prev};
    wire [8:0]        adif = dif9[8] ? (9'd0 - dif9) : dif9;
    // 正半周判据: x>0（0 归入非正, 与训练脚本的 xn>0 一致）
    wire pos_d = (din[7]  == 1'b0) && (din  != 8'sd0);
    wire pos_p = (prev[7] == 1'b0) && (prev != 8'sd0);

    // ---- 共用顺序除法器: 40 位 / 26 位, 40 拍 ----
    // 恢复余数法: r 从 0 开始, 每拍把**被除数的下一位**移进 r 的最低位,
    //   再与除数比较, 够减则减、商位记 1, 否则记 0。共 40 拍出 40 位商。
    // ★ 原来写成 {dv_r[38:0], 1'b0} —— 只移位不进被除数的位, dv_n 设了也没用,
    //   结果余数永远是 0, 所有商都是 0（实测 f1~f4 全 0, f0/f5 这种纯移位反倒对）。
    reg [39:0] dv_n, dv_nsh, dv_r, dv_q, dv_cap;
    reg [25:0] dv_d;
    reg [5:0]  dv_i;
    reg        dv_bsy;
    wire [40:0] dv_sh = {dv_r[38:0], dv_nsh[39]};   // 移入 N 的最高位
    wire        dv_ge = (dv_sh[39:0] >= {14'd0, dv_d});

    // ---- 开方: 32 位 -> 16 位, 16 拍（逐位试减）----
    // [10-17 修复·重要] 原来用"移位-试减 b=(b<<2)|1"那套写法, 推导有误
    //   （Python 复现同一算法, sqrt(1e6) 只得到 63, 真值 1000）, 且中途还漏接输入位。
    //   换成经典逐位试减:
    //     res=0, bit=1<<30
    //     每步: if (n >= res+bit) { n -= res+bit; res = (res>>1)+bit; }
    //           else                 res = res>>1;
    //           bit >>= 2
    //   16 步后 res 即 floor(sqrt(n))。Python 验证 6 个测试值误差全为 0。
    reg [31:0] sq_n, sq_res, sq_bit;
    reg [15:0] sq_cap;
    reg [5:0]  sq_i;
    reg        sq_bsy;
    wire [32:0] sq_sum = {1'b0, sq_res} + {1'b0, sq_bit};
    wire        sq_ge  = ({1'b0, sq_n} >= sq_sum);
    // [10-17 修复] 标准算法 res = (res>>1) + bit。原写成 {1'b0, sq_res[30:0]} + sq_bit,
    //   那只是清最高位、**不是右移**, 于是 res 一路累积变大
    //   （实测 sqrt(5953720) 得 17540, 真值 2440）。
    wire [31:0] sq_rnx = sq_ge ? ((sq_res >> 1) + sq_bit) : (sq_res >> 1);

    // ---- 运算序号与"已启动"标志 ----
    reg [3:0]  op_idx;
    reg        op_run;
    reg [15:0] r_sqrt;
    // [10-17 修复] |sumx| 必须用**组合 wire**: 原来写成 reg 非阻塞赋值,
    //   紧接着的 dv_n 读到的是旧值(复位值 0) -> f1 永远是 0。
    // [10-17 修复] {1'b0, a_s} 是**零扩展**, 不是符号扩展 —— 负数取绝对值会变成巨大正数
    //   (实测 a_s=-190 得到 131262)。正确做法: 先赋给 signed 变量自动符号扩展, 再取负。
    wire signed [21:0] a_s22  = a_s;                                  // 自动符号扩展
    wire [21:0]        sx_abs = a_s22[21] ? (22'd0 - a_s22) : a_s22;  // |sumx|
    reg [39:0] d4;                    // sumx^4/sumx^2

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
            dv_n <= 40'd0; dv_nsh <= 40'd0; dv_r <= 40'd0; dv_q <= 40'd0; dv_d <= 26'd0;
            dv_i <= 6'd0; dv_bsy <= 1'b0; dv_cap <= 40'd0;
            sq_n <= 32'd0; sq_res <= 32'd0; sq_bit <= 32'd0;
            sq_i <= 6'd0; sq_bsy <= 1'b0; sq_cap <= 16'd0;
            op_idx <= 4'd0; op_run <= 1'b0; r_sqrt <= 16'd0; d4 <= 40'd0;
        end
        else begin
            done   <= 1'b0;
            dbg_st <= st;
            dbg_op <= op_idx;

            //======== 除法器推进 ========
            if (dv_bsy) begin
                dv_r   <= dv_ge ? (dv_sh[39:0] - {14'd0, dv_d}) : dv_sh[39:0];
                dv_q   <= {dv_q[38:0], dv_ge};
                dv_nsh <= dv_nsh << 1;                  // 被除数逐位左移
                if (dv_i == 6'd39) dv_bsy <= 1'b0;
                else               dv_i   <= dv_i + 6'd1;
            end
            // 最后一步: 商锁存
            if (dv_end) dv_cap <= {dv_q[38:0], dv_ge};

            //======== 开方推进（逐位试减）========
            if (sq_bsy) begin
                sq_n   <= sq_ge ? (sq_n - sq_sum[31:0]) : sq_n;
                sq_res <= sq_rnx;
                sq_bit <= sq_bit >> 2;
                if (sq_i == 6'd15) begin
                    sq_bsy <= 1'b0;
                    sq_cap <= sq_rnx[15:0];
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
                            // [10-17 修复] 过零判据要与训练一致: Python 用 (x > 0),
                            //   x=0 算非正。原来只比符号位, 把 0 当成了正数,
                            //   实测过零数偏少 6 个（f5 差 128~192）。
                            if (pos_d != pos_p) a_zc <= a_zc + 11'd1;
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
                                4'd0: begin   // ① f1 = |sumx|*32 / pk
                                    dv_n <= {18'd0, sx_abs} << 5;               // 18+22 = 40 位
                                    dv_nsh <= {18'd0, sx_abs} << 5;
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd1: begin   // ② f4 = sum|dx|*64 / pk
                                    dv_n <= {20'd0, a_sl} << 6;
                                    dv_nsh <= {20'd0, a_sl} << 6;
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd2: begin   // ③ 开方 √(sumx^2)
                                    sq_n   <= {5'd0, a_sq};
                                    sq_res <= 32'd0;
                                    sq_bit <= 32'h4000_0000;   // 1<<30
                                    sq_i   <= 6'd0; sq_bsy <= 1'b1;
                                end
                                4'd3: begin   // ④ f3 = √(sumx^2)*1024 / pk
                                    dv_n <= {24'd0, sq_cap} << 10;
                                    dv_nsh <= {24'd0, sq_cap} << 10;
                                    dv_d <= {17'd0, pk};
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd4: begin   // ⑤ d4 = sumx^4 / sumx^2
                                    dv_n <= a_x4;
                                    dv_nsh <= a_x4;
                                    dv_d <= {1'b0, a_sq[24:0]};                 // 26 位(a_sq≤16.8e6 < 2^25)
                                    dv_r <= 40'd0; dv_q <= 40'd0; dv_i <= 6'd0; dv_bsy <= 1'b1;
                                end
                                4'd5: begin   // ⑥ f2 = d4*2^25 / (3·sumx^2)
                                    dv_n <= d4 << 25;
                                    dv_nsh <= d4 << 25;
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
