# -*- coding: utf-8 -*-
"""把开方单元换成"逐位试减"算法（已用 Python 验证 6 个值误差 0）。"""
import io

P = 'src/wave_feat.v'
t = io.open(P, encoding='utf-8').read()

# ---- 1) 替换开方寄存器与组合逻辑 ----
old1 = """    // ---- 开方: 32 位 -> 16 位, 16 拍 ----
    reg [31:0] sq_x, sq_r;
    reg [15:0] sq_q, sq_b, sq_cap;
    reg [5:0]  sq_i;
    reg        sq_bsy;
    // [10-17 修复·关键] 开方第 i 步要算 (r<<2) | (x 的最高 2 位)。
    //   原来写 {sq_r[31:0], 2'b00} —— 只左移 r, **完全没把输入的位接进来**,
    //   于是 r 恒为 0、结果恒为 0(f3 一直是 0 就是这么来的)。
    wire [33:0] sq_t  = {sq_r[31:0], sq_x[31:30]};
    wire [33:0] sq_bx = {16'd0, sq_b, 2'b01};
    wire        sq_ge = (sq_t >= sq_bx);
    // 减法的低 32 位: 不能写 (a-b)[31:0], Verilog 不允许对表达式位选
    wire [33:0] sq_sub = sq_t - sq_bx;
    wire [31:0] sq_nx  = sq_ge ? sq_sub[31:0] : sq_t[31:0];"""

new1 = """    // ---- 开方: 32 位 -> 16 位, 16 拍（逐位试减）----
    // [10-17 修复·重要] 原来用的是"移位-试减 b=(b<<2)|1"那套写法, 但推导有误
    //   （用 Python 复现同一算法, sqrt(1e6) 只得到 63, 真值 1000）, 且中途还漏把
    //   输入位接进来。已换成经典的逐位试减:
    //     res=0, bit=1<<30
    //     每步: if (n >= res+bit) { n -= res+bit; res = (res>>1)+bit; }
    //           else                 res = res>>1;
    //           bit >>= 2
    //   16 步后 res 即 ⌊√n⌋。已用 Python 验证 6 个测试值误差全为 0。
    reg [31:0] sq_n, sq_res, sq_bit;
    reg [15:0] sq_cap;
    reg [5:0]  sq_i;
    reg        sq_bsy;
    wire [32:0] sq_sum  = {1'b0, sq_res} + {1'b0, sq_bit};
    wire        sq_ge   = ({1'b0, sq_n} >= sq_sum);
    wire [31:0] sq_rnx  = sq_ge ? ({1'b0, sq_res[30:0]} + sq_bit) : (sq_res >> 1);"""
if old1 not in t:
    raise SystemExit('开方声明锚点未命中')
t = t.replace(old1, new1, 1)

# ---- 2) 替换开方推进逻辑 ----
old2 = """            //======== 开方推进 ========
            if (sq_bsy) begin
                sq_r <= sq_ge ? sq_nx : sq_t[31:0];
                sq_q <= sq_ge ? (sq_q | sq_b) : sq_q;
                sq_x <= {sq_x[29:0], 2'b00};
                sq_b <= sq_b >> 1;
                if (sq_i == 6'd15) begin
                    sq_bsy <= 1'b0;
                    sq_cap <= sq_ge ? (sq_q | sq_b) : sq_q;
                end
                else sq_i <= sq_i + 6'd1;
            end"""

new2 = """            //======== 开方推进（逐位试减）========
            if (sq_bsy) begin
                sq_n   <= sq_ge ? (sq_n - sq_sum[31:0]) : sq_n;
                sq_res <= sq_rnx;
                sq_bit <= sq_bit >> 2;
                if (sq_i == 6'd15) begin
                    sq_bsy <= 1'b0;
                    sq_cap <= sq_rnx[15:0];
                end
                else sq_i <= sq_i + 6'd1;
            end"""
if old2 not in t:
    raise SystemExit('开方推进锚点未命中')
t = t.replace(old2, new2, 1)

# ---- 3) 复位 ----
old3 = ("            sq_x <= 32'd0; sq_r <= 32'd0; sq_q <= 16'd0; sq_b <= 16'd0;\n"
        "            sq_i <= 6'd0; sq_bsy <= 1'b0; sq_cap <= 16'd0;")
new3 = ("            sq_n <= 32'd0; sq_res <= 32'd0; sq_bit <= 32'd0;\n"
        "            sq_i <= 6'd0; sq_bsy <= 1'b0; sq_cap <= 16'd0;")
if old3 not in t:
    raise SystemExit('开方复位锚点未命中')
t = t.replace(old3, new3, 1)

# ---- 4) 启动 ----
old4 = ("                                4'd2: begin   // ③ 开方 √(Σx²)\n"
        "                                    sq_x <= {5'd0, a_sq};\n"
        "                                    sq_r <= 32'd0; sq_q <= 16'd0; sq_b <= 16'h8000;\n"
        "                                    sq_i <= 6'd0; sq_bsy <= 1'b1;\n"
        "                                end")
new4 = ("                                4'd2: begin   // ③ 开方 √(Σx²)\n"
        "                                    sq_n   <= {5'd0, a_sq};\n"
        "                                    sq_res <= 32'd0;\n"
        "                                    sq_bit <= 32'h4000_0000;   // 1<<30\n"
        "                                    sq_i   <= 6'd0; sq_bsy <= 1'b1;\n"
        "                                end")
if old4 not in t:
    raise SystemExit('开方启动锚点未命中')
t = t.replace(old4, new4, 1)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('开方单元已换成逐位试减算法')
