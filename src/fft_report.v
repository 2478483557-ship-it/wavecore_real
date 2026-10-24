//===========================================================================
// 模块名   : fft_report (v1.1)
// 功能     : FFT 谱峰串口上报 —— 主峰 "S=xxxxxxxHz", 第二峰 "A=xxxxxxxHz"
// 仲裁     : 与测量行共用 TX, 只在测量行空闲窗口(3k~350k 拍)内整行发送
// 依赖     : uart_tx / bin2bcd
// 作者     : WaveCore 队长 | 日期: 2026-09-05
//===========================================================================

module fft_report (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        meas_busy,
    input  wire        fft_done,
    input  wire [23:0] fft_hz,
    input  wire        fft_done2,
    input  wire [23:0] fft_hz2,
    output wire        uart_txd,
    output wire        fft_active,
    // [10-24] 调试回读(0x9E): 把"为什么还不发 S="的依据送出去
    //   dbg_state = {window_ok, ext_hold, p_s, p_a, active_r, state[2:0]}
    output wire [7:0]  dbg_state,
    output wire [18:0] dbg_idle,
    input  wire        ext_hold     // 1=波形帧占用 TX, 本模块暂停开新行
);

    //================ 串口 ================
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    //================ BCD(主/次各一) ================
    wire [27:0] bcd1, bcd2;
    wire        d1, d2;
    reg         c1_start, c2_start;
    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b1 (
        .clk(clk), .rst_n(rst_n), .start(c1_start),
        .bin(fft_hz), .bcd(bcd1), .done(d1));
    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2 (
        .clk(clk), .rst_n(rst_n), .start(c2_start),
        .bin(fft_hz2), .bcd(bcd2), .done(d2));

    // 行字符: mode 0=主峰(S=), 1=第二峰(A=); 长度 11: 前缀+'+7数字+\r\n
    function [7:0] line_char(input [3:0] i, input mode, input [27:0] b);
        case (i)
            4'd0:  line_char = (mode == 1'b0) ? 8'h53 : 8'h41;   // 'S' 或 'A'
            4'd1:  line_char = 8'h3D;                             // '='
            4'd2:  line_char = 8'd48 + b[27:24];
            4'd3:  line_char = 8'd48 + b[23:20];
            4'd4:  line_char = 8'd48 + b[19:16];
            4'd5:  line_char = 8'd48 + b[15:12];
            4'd6:  line_char = 8'd48 + b[11:8];
            4'd7:  line_char = 8'd48 + b[7:4];
            4'd8:  line_char = 8'd48 + b[3:0];
            4'd9:  line_char = 8'h0D;
            default: line_char = 8'h0A;                           // 4'd10
        endcase
    endfunction

    //================ 状态 ================
    reg [2:0] state;
    localparam S_WAIT=3'd0, S_C1=3'd1, S_C2=3'd2, S_SEND=3'd3;
    reg [3:0] idx;
    reg       guard;
    reg       mode;        // 0=S行 1=A行
    reg       p_s, p_a;    // 待发主/次行
    reg       active_r;
    reg [18:0] idle_cnt;
    reg [27:0] cur_bcd;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) idle_cnt <= 19'd0;
        else if (meas_busy) idle_cnt <= 19'd0;
        else if (idle_cnt < 19'd400_000) idle_cnt <= idle_cnt + 19'd1;
    end
    wire window_ok = !meas_busy && (idle_cnt >= 19'd3000) && (idle_cnt <= 19'd350_000);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_WAIT;
            tx_byte  <= 8'd0;
            tx_start <= 1'b0;
            guard    <= 1'b0;
            mode     <= 1'b0;
            p_s      <= 1'b0;
            p_a      <= 1'b0;
            idx      <= 4'd0;
            c1_start <= 1'b0;
            c2_start <= 1'b0;
            active_r <= 1'b0;
            cur_bcd  <= 28'd0;
        end
        else begin
            tx_start  <= 1'b0;
            c1_start  <= 1'b0;
            c2_start  <= 1'b0;

            if (fft_done)  p_s <= 1'b1;
            if (fft_done2) p_a <= 1'b1;

            case (state)
                S_WAIT: begin
                    if (window_ok && !ext_hold) begin
                        if (p_s) begin
                            p_s <= 1'b0;
                            c1_start <= 1'b1;
                            state <= S_C1;
                        end
                        else if (p_a) begin
                            p_a <= 1'b0;
                            c2_start <= 1'b1;
                            state <= S_C2;
                        end
                    end
                end
                S_C1: if (d1) begin
                            mode <= 1'b0;
                            cur_bcd <= bcd1;
                            state <= S_SEND;
                            idx <= 4'd0; guard <= 1'b0;
                            active_r <= 1'b1;
                        end
                S_C2: if (d2) begin
                            mode <= 1'b1;
                            cur_bcd <= bcd2;
                            state <= S_SEND;
                            idx <= 4'd0; guard <= 1'b0;
                            active_r <= 1'b1;
                        end
                S_SEND: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx == 4'd11) begin
                            active_r <= 1'b0;
                            state <= S_WAIT;
                        end
                        else begin
                            tx_byte <= line_char(idx, mode, cur_bcd);
                            tx_start <= 1'b1;
                            guard <= 1'b1;
                            idx  <= idx + 4'd1;
                        end
                    end
                end
                default: state <= S_WAIT;
            endcase
        end
    end

    assign fft_active = active_r;
    assign dbg_state = {window_ok, ext_hold, p_s, p_a, active_r, state};
    assign dbg_idle  = idle_cnt;

endmodule
