//===========================================================================
// 模块名   : measure_report v3.2 (正式版)
// 输出     : "F=0100000Hz V=255\r\n" + "D=050.0% W=00500us\r\n" (39字节连发)
// 说明     : duty/width 来自 freq_meter v4.0 计窗统计法(对毛刺免疫)
// 作者     : WaveCore 队长 | 日期: 2026-09-16 | 版本: v3.2
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
    input  wire [31:0] dbg_p_tick
);

    //================ 频率/Vpp BCD ================
    wire [27:0] freq_bcd;   wire freq_done;   reg freq_start;
    wire [11:0] vpp_bcd;    wire vpp_done;    reg vpp_start;

    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2f (
        .clk(clk), .rst_n(rst_n), .start(freq_start),
        .bin(freq_hz), .bcd(freq_bcd), .done(freq_done) );
    bin2bcd #(.IN_W(8), .OUT_W(12)) u_b2v (
        .clk(clk), .rst_n(rst_n), .start(vpp_start),
        .bin({8'd0, vpp}), .bcd(vpp_bcd), .done(vpp_done) );

    //================ 锁存 ================
    reg [15:0] duty_s;
    reg [19:0] width_s;
    // [9/20] TY 可信闸门: 频率稳定(±1.5%) 且 ≤25kHz 才给识别结论
    reg [23:0] prev_f;
    wire [23:0] f_diff = (freq_hz > prev_f) ? (freq_hz - prev_f) : (prev_f - freq_hz);
    wire f_stable = (prev_f == 24'd0) || (f_diff <= (prev_f >> 6) + 24'd16);
    wire ty_ok = (freq_hz <= 24'd25000) && f_stable;
    wire [1:0] ty_now = ty_ok ? wave_type : 2'd3;

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

    //================ 39 字节字符表 ================
    reg [5:0] idx;
    wire [7:0] ch = char_at(idx);
    function [7:0] char_at(input [5:0] i);
        case (i)
            6'd0:  char_at = 8'h46;
            6'd1:  char_at = 8'h3D;
            6'd2:  char_at = 8'd48 + fd10(freq_bcd, 3'd6);
            6'd3:  char_at = 8'd48 + fd10(freq_bcd, 3'd5);
            6'd4:  char_at = 8'd48 + fd10(freq_bcd, 3'd4);
            6'd5:  char_at = 8'd48 + fd10(freq_bcd, 3'd3);
            6'd6:  char_at = 8'd48 + fd10(freq_bcd, 3'd2);
            6'd7:  char_at = 8'd48 + fd10(freq_bcd, 3'd1);
            6'd8:  char_at = 8'd48 + fd10(freq_bcd, 3'd0);
            6'd9:  char_at = 8'h48;
            6'd10: char_at = 8'h7A;
            6'd11: char_at = 8'h20;
            6'd12: char_at = 8'h56;
            6'd13: char_at = 8'h3D;
            6'd14: char_at = 8'd48 + fd10({16'd0, vpp_bcd}, 3'd2);
            6'd15: char_at = 8'd48 + fd10({16'd0, vpp_bcd}, 3'd1);
            6'd16: char_at = 8'd48 + fd10({16'd0, vpp_bcd}, 3'd0);
            6'd17: char_at = 8'h0D;
            6'd18: char_at = 8'h0A;
            6'd19: char_at = 8'h44;                        // 'D'
            6'd20: char_at = 8'h3D;                        // '='
            6'd21: char_at = 8'd48 + dg_d(duty_s, 2'd3);
            6'd22: char_at = 8'd48 + dg_d(duty_s, 2'd2);
            6'd23: char_at = 8'd48 + dg_d(duty_s, 2'd1);
            6'd24: char_at = 8'h2E;                        // '.'
            6'd25: char_at = 8'd48 + dg_d(duty_s, 2'd0);
            6'd26: char_at = 8'h25;                        // '%'
            6'd27: char_at = 8'h20;
            6'd28: char_at = 8'h57;                        // 'W'
            6'd29: char_at = 8'h3D;                        // '='
            6'd30: char_at = 8'd48 + dg_w(width_s, 3'd4);
            6'd31: char_at = 8'd48 + dg_w(width_s, 3'd3);
            6'd32: char_at = 8'd48 + dg_w(width_s, 3'd2);
            6'd33: char_at = 8'd48 + dg_w(width_s, 3'd1);
            6'd34: char_at = 8'd48 + dg_w(width_s, 3'd0);
            6'd35: char_at = 8'h75;                        // 'u'
            6'd36: char_at = 8'h73;                        // 's'
            6'd37: char_at = 8'h0D;
            6'd38: char_at = 8'h0A;                        // 38 LF
            6'd39: char_at = 8'h54;                        // 'T'
            6'd40: char_at = 8'h59;                        // 'Y'
            6'd41: char_at = 8'h3D;                        // '='
            6'd42: char_at = 8'd48 + {2'd0, ty_now};       // 0/1/2/3(带闸门)
            6'd43: char_at = 8'h0D;
            6'd44: char_at = 8'h0A;
            default: char_at = 8'h0A;
        endcase
    endfunction

    //================ 状态机 ================
    localparam S_WAIT = 3'd0;
    localparam S_CF   = 3'd1;
    localparam S_WF   = 3'd2;
    localparam S_CV   = 3'd3;
    localparam S_WV   = 3'd4;
    localparam S_SEND = 3'd5;

    reg [2:0] state;
    reg       guard;

    assign dbg_fsm = {state, idx[4:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_WAIT;
            freq_start <= 1'b0;
            vpp_start  <= 1'b0;
            tx_start   <= 1'b0;
            idx        <= 6'd0;
            guard      <= 1'b0;
            duty_s     <= 16'd0;
            width_s    <= 20'd0;
        end
        else begin
            tx_start   <= 1'b0;
            freq_start <= 1'b0;
            vpp_start  <= 1'b0;

            case (state)
                S_WAIT: if (meas_done && !ext_hold) begin
                            prev_f <= freq_hz;
                            freq_start <= 1'b1;
                            state <= S_CF;
                        end
                S_CF:   state <= S_WF;
                S_WF:   if (freq_done) begin
                            vpp_start <= 1'b1;
                            state <= S_CV;
                        end
                S_CV:   state <= S_WV;
                S_WV:   if (vpp_done) begin
                            duty_s  <= duty_x10;
                            width_s <= width_us;
                            idx   <= 6'd0;
                            guard <= 1'b0;
                            state <= S_SEND;
                        end
                S_SEND: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx == 6'd45) begin
                            state <= S_WAIT;                 // 45字节(F行+V行+TY行)
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
