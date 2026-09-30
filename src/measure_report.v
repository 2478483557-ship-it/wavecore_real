//===========================================================================
// 模块名   : measure_report v3.3
// 输出     : "F=0100000Hz V=1086\r\n" + "D=050.0% W=00500us\r\n" + "TY=1\r\n"
//            共 46 字节。
//
// v3.3 相对 v3.2 的改动(2026-09-30):
//   1) V 字段由 3 位 LSB 改成 4 位 mV。原来 "V=139" 是 ADC 码值, 对外行不通;
//      现在 "V=1086" 是 1086mV, 而且留了 4 位, 满量程 9999mV 不会撞顶。
//   2) V 的换算交给 vpp_mv 模块(8x16 乘法 + 饱和), 不再走 bin2bcd 的 8->12 位转换。
//      **顺带省了资源**: 原来的 u_b2v(bin2bcd) 整块删掉, 数字位改用已有的 dg_w
//      常量除法函数生成 —— 它在生成 W 字段时本来就要综合一遍, 复用比新开一套 BCD 便宜。
//   3) 状态机少一态: 不再等 vpp_bcd 转换完成, 所以 S_CV 取消。
//
// 【为什么 mV 要 4 位而不是 3 位】
//   3 位最大 999 —— 实测正弦 Vpp 就已经 1.0V 出头(139LSB x 7.8125mV),
//   折成 mV 是 1086, 3 位直接溢出。这不是"显示好看", 是正确性问题。
//
// 【为什么 V 最后一位是"1"而不是"0"就该怀疑】
//   mv_r 每帧更新一次, 由 v_s(3窗中值后的 Vpp) 组合算出。
//   若 V 长期是个漂亮的整数(如 1000、2000), 反而说明乘法的 KN 档位不对。
//
// 说明     : duty/width 来自 freq_meter v4.0 计窗统计法(对毛刺免疫)
// 作者     : WaveCore 队长 | 日期: 2026-09-30 | 版本: v3.3
//===========================================================================

module measure_report (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        meas_done,
    input  wire [23:0] freq_hz,
    input  wire [7:0]  vpp,
    input  wire        meas_done2,
    input  wire [15:0] duty_x10,
    input  wire [19:0] width_us,
    output wire        uart_txd,
    input  wire [1:0]  wave_type,   // 波形识别: 0方波 1正弦 2三角 3其他
    output wire        meas_busy,
    input  wire        ext_hold,
    output wire [7:0]  dbg_fsm,
    input  wire [31:0] dbg_h_tick,
    input  wire [31:0] dbg_p_tick,
    input  wire [15:0] cal_kn       // [0x8C] 每 LSB 多少 mV x1024 (Q10), 默认 8000
);

    //================ 频率 BCD ================
    wire [27:0] freq_bcd;   wire freq_done;   reg freq_start;

    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2f (
        .clk(clk), .rst_n(rst_n), .start(freq_start),
        .bin(freq_hz), .bcd(freq_bcd), .done(freq_done) );

    //================ 锁存 ================
    reg [15:0] duty_s;
    reg [19:0] width_s;
    // [9/20] 3窗中值平滑: D/W/V 抗"偶发坏窗"(F 保持即时)
    reg [7:0]  v_s;
    reg [7:0]  vd1, vd2;
    reg [15:0] dd1, dd2;
    reg [19:0] wd1, wd2;
    function [7:0] med8(input [7:0] a,b,c);
        med8 = (a<b) ? ((b<c)?b:((a<c)?c:a)) : ((a<c)?a:((b<c)?c:b));
    endfunction
    function [15:0] med16(input [15:0] a,b,c);
        med16 = (a<b) ? ((b<c)?b:((a<c)?c:a)) : ((a<c)?a:((b<c)?c:b));
    endfunction
    function [19:0] med20(input [19:0] a,b,c);
        med20 = (a<b) ? ((b<c)?b:((a<c)?c:a)) : ((a<c)?a:((b<c)?c:b));
    endfunction
    // [9/20] TY 可信闸门: 频率稳定(±1.5%) 且 ≤25kHz 才给识别结论
    reg [23:0] prev_f;
    wire [23:0] f_diff = (freq_hz > prev_f) ? (freq_hz - prev_f) : (prev_f - freq_hz);
    wire f_stable = (prev_f == 24'd0) || (f_diff <= (prev_f >> 6) + 24'd16);
    wire ty_ok = (freq_hz <= 24'd25000) && f_stable;
    wire [1:0] ty_now = ty_ok ? wave_type : 2'd3;

    //================ Vpp: LSB -> mV ================
    // 纯组合换算(输入 v_s 是寄存器, 输出到 mv_r 寄存器), 组合链被夹在寄存器之间
    wire [13:0] mv_calc;
    vpp_mv u_vpp_mv (
        .vpp_lsb (v_s),
        .kn      (cal_kn),
        .mv      (mv_calc)
    );
    reg [13:0] mv_r;                 // 每帧锁一次, 供字符表稳定取用
    wire [19:0] mv20 = {6'd0, mv_r}; // dg_w 吃 20 位, 高位补 0

    //================ 数字位生成 ================
    function [3:0] fd10(input [27:0] v, input [3:0] idx);
        fd10 = v[idx*4 +: 4];
    endfunction
    function [3:0] dg_d(input [15:0] v, input [1:0] pos);
        case (pos)
            2'd3: dg_d = (v >= 16'd1000) ? 4'd1 : 4'd0;
            2'd2: dg_d = (v / 16'd100) % 16'd10;
            2'd1: dg_d = (v / 16'd10) % 16'd10;
            default: dg_d = v % 16'd10;
        endcase
    endfunction
    // 4 位 mV 用 pos=3..0; W 字段 5 位用 pos=4..0
    function [3:0] dg_w(input [19:0] v, input [2:0] pos);
        case (pos)
            3'd4: dg_w = (v / 20'd10000);
            3'd3: dg_w = (v / 20'd1000) % 20'd10;
            3'd2: dg_w = (v / 20'd100) % 20'd10;
            3'd1: dg_w = (v / 20'd10) % 20'd10;
            default: dg_w = v % 20'd10;
        endcase
    endfunction

    //================ 串口 ================
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));
    assign meas_busy = tx_busy;

    //================ 46 字节字符表 ================
    //  0..18  F=xxxxxxxHz V=xxxx\r\n
    // 19..39  D=xxx.x% W=xxxxxus\r\n
    // 40..45  TY=x\r\n
    reg [5:0] idx;
    wire [7:0] ch = char_at(idx);
    function [7:0] char_at(input [5:0] i);
        case (i)
            // ---- 第 1 行: 频率 + 电压(mV, 4 位) ----
            6'd0:  char_at = 8'h46;                        // 'F'
            6'd1:  char_at = 8'h3D;                        // '='
            6'd2:  char_at = 8'd48 + fd10(freq_bcd, 3'd6);
            6'd3:  char_at = 8'd48 + fd10(freq_bcd, 3'd5);
            6'd4:  char_at = 8'd48 + fd10(freq_bcd, 3'd4);
            6'd5:  char_at = 8'd48 + fd10(freq_bcd, 3'd3);
            6'd6:  char_at = 8'd48 + fd10(freq_bcd, 3'd2);
            6'd7:  char_at = 8'd48 + fd10(freq_bcd, 3'd1);
            6'd8:  char_at = 8'd48 + fd10(freq_bcd, 3'd0);
            6'd9:  char_at = 8'h48;                        // 'H'
            6'd10: char_at = 8'h7A;                        // 'z'
            6'd11: char_at = 8'h20;                        // ' '
            6'd12: char_at = 8'h56;                        // 'V'
            6'd13: char_at = 8'h3D;                        // '='
            6'd14: char_at = 8'd48 + dg_w(mv20, 3'd3);     // 千位
            6'd15: char_at = 8'd48 + dg_w(mv20, 3'd2);     // 百位
            6'd16: char_at = 8'd48 + dg_w(mv20, 3'd1);     // 十位
            6'd17: char_at = 8'd48 + dg_w(mv20, 3'd0);     // 个位
            6'd18: char_at = 8'h0D;                        // '\r'
            // ---- 第 2 行: 占空比 + 脉宽 ----
            6'd19: char_at = 8'h0A;                        // '\n'
            6'd20: char_at = 8'h44;                        // 'D'
            6'd21: char_at = 8'h3D;                        // '='
            6'd22: char_at = 8'd48 + dg_d(duty_s, 2'd3);
            6'd23: char_at = 8'd48 + dg_d(duty_s, 2'd2);
            6'd24: char_at = 8'd48 + dg_d(duty_s, 2'd1);
            6'd25: char_at = 8'h2E;                        // '.'
            6'd26: char_at = 8'd48 + dg_d(duty_s, 2'd0);
            6'd27: char_at = 8'h25;                        // '%'
            6'd28: char_at = 8'h20;                        // ' '
            6'd29: char_at = 8'h57;                        // 'W'
            6'd30: char_at = 8'h3D;                        // '='
            6'd31: char_at = 8'd48 + dg_w(width_s, 3'd4);
            6'd32: char_at = 8'd48 + dg_w(width_s, 3'd3);
            6'd33: char_at = 8'd48 + dg_w(width_s, 3'd2);
            6'd34: char_at = 8'd48 + dg_w(width_s, 3'd1);
            6'd35: char_at = 8'd48 + dg_w(width_s, 3'd0);
            6'd36: char_at = 8'h75;                        // 'u'
            6'd37: char_at = 8'h73;                        // 's'
            6'd38: char_at = 8'h0D;                        // '\r'
            // ---- 第 3 行: 波形类型 ----
            6'd39: char_at = 8'h0A;                        // '\n'
            6'd40: char_at = 8'h54;                        // 'T'
            6'd41: char_at = 8'h59;                        // 'Y'
            6'd42: char_at = 8'h3D;                        // '='
            6'd43: char_at = 8'd48 + {2'd0, ty_now};       // 0/1/2/3(带闸门)
            6'd44: char_at = 8'h0D;                        // '\r'
            6'd45: char_at = 8'h0A;                        // '\n'
            default: char_at = 8'h0A;
        endcase
    endfunction

    //================ 状态机 ================
    localparam S_WAIT = 3'd0;
    localparam S_CF   = 3'd1;   // 等频率 BCD
    localparam S_WF   = 3'd2;
    localparam S_WV   = 3'd3;   // 锁 D/W/mV 并出发
    localparam S_SEND = 3'd4;

    reg [2:0] state;
    reg       guard;

    assign dbg_fsm = {state, idx[4:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_WAIT;
            freq_start <= 1'b0;
            tx_start   <= 1'b0;
            idx        <= 6'd0;
            guard      <= 1'b0;
            duty_s     <= 16'd0;
            width_s    <= 20'd0;
            mv_r       <= 14'd0;
            v_s<=8'd0; vd1<=8'd0; vd2<=8'd0;
            dd1<=16'd0; dd2<=16'd0; wd1<=20'd0; wd2<=20'd0;
        end
        else begin
            tx_start   <= 1'b0;
            freq_start <= 1'b0;

            case (state)
                S_WAIT: if (meas_done && !ext_hold) begin
                            prev_f <= freq_hz;
                            // V 3窗中值
                            v_s  <= med8(vpp, vd1, vd2);
                            vd2  <= vd1;
                            vd1  <= vpp;
                            freq_start <= 1'b1;
                            state <= S_CF;
                        end
                S_CF:   state <= S_WF;
                S_WF:   if (freq_done) state <= S_WV;
                S_WV:   begin
                            // D/W 3窗中值
                            duty_s  <= med16(duty_x10, dd1, dd2);
                            width_s <= med20(width_us, wd1, wd2);
                            dd2     <= dd1;  dd1 <= duty_x10;
                            wd2     <= wd1;  wd1 <= width_us;
                            mv_r    <= mv_calc;      // 本帧的 mV 结果, 锁一拍给字符表
                            idx     <= 6'd0;
                            guard   <= 1'b0;
                            state   <= S_SEND;
                        end
                S_SEND: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx == 6'd46) begin
                            state <= S_WAIT;                 // 46 字节发完(F行+V行+TY行)
                        end
                        else begin
                            tx_byte  <= ch;
                            tx_start <= 1'b1;
                            guard    <= 1'b1;
                            idx      <= idx + 6'd1;
                        end
                    end
                end
                default: state <= S_WAIT;
            endcase
        end
    end

endmodule
