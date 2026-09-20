//===========================================================================
// 模块名   : self_fft_report v2.0 (干净正式版)
// 功能     : 0x8A 触发后, 依次上报前三峰: "SF=/S2=/S3=" 三行(各14字节)
// 仲裁     : 仅等总线空闲(!m_busy & !fft_act & !wav_act)后开始, 期间占用TX
// 父模块   : board_top (u_sfrpt)
// 作者     : WaveCore 队长 | 日期: 2026-09-19
//===========================================================================
module self_fft_report (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] res_freq,    // 第一峰 Hz
    input  wire [23:0] res_f2,      // 第二峰 Hz
    input  wire [23:0] res_f3,      // 第三峰 Hz
    input  wire        res_done,    // 完成脉冲
    input  wire        m_busy,      // 测量行忙
    input  wire        fft_act,     // 谱峰行忙
    input  wire        wav_act,     // 波形帧忙
    output wire        uart_txd,
    output wire        sf_active    // 占用TX标志
);
    // ---- 选择当前峰 ----
    reg  [1:0]  k_sel;              // 0=SF 1=S2 2=S3
    wire [23:0] cur = (k_sel==2'd0) ? res_freq :
                      (k_sel==2'd1) ? res_f2   : res_f3;

    // ---- 频率 BCD ----
    wire [27:0] f_bcd; wire f_done; reg f_start;
    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2f (
        .clk(clk), .rst_n(rst_n), .start(f_start),
        .bin(cur), .bcd(f_bcd), .done(f_done) );

    function [3:0] d10(input [27:0] v, input [3:0] idx);
        d10 = v[idx*4 +: 4];
    endfunction

    // ---- 串口 ----
    reg [7:0] tx_byte; reg tx_start; wire tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    // ---- 行字符: "S?" + "=" + 7位数字 + "Hz\r\n" = 14 字节 ----
    reg [3:0] idx;
    wire [7:0] ch = char_at(idx);
    function [7:0] char_at(input [3:0] i);
        case (i)
            4'd0: char_at = 8'h53;                         // 'S'
            4'd1: char_at = (k_sel==2'd0) ? 8'h46 :        // 'F'
                            (k_sel==2'd1) ? 8'h32 :        // '2'
                                            8'h33;         // '3'
            4'd2: char_at = 8'h3D;                         // '='
            4'd3: char_at = 8'd48 + d10(f_bcd, 3'd6);
            4'd4: char_at = 8'd48 + d10(f_bcd, 3'd5);
            4'd5: char_at = 8'd48 + d10(f_bcd, 3'd4);
            4'd6: char_at = 8'd48 + d10(f_bcd, 3'd3);
            4'd7: char_at = 8'd48 + d10(f_bcd, 3'd2);
            4'd8: char_at = 8'd48 + d10(f_bcd, 3'd1);
            4'd9: char_at = 8'd48 + d10(f_bcd, 3'd0);
            4'd10:char_at = 8'h48;                         // 'H'
            4'd11:char_at = 8'h7A;                         // 'z'
            4'd12:char_at = 8'h0D;
            default: char_at = 8'h0A;                      // 13 = LF
        endcase
    endfunction

    // ---- 状态机 ----
    localparam S_WAIT=2'd0, S_CF=2'd1, S_WF=2'd2, S_SEND=2'd3;
    reg [1:0] state; reg guard;
    reg       pending;      // 结果待发

    assign sf_active = (state != S_WAIT);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= S_WAIT;
            f_start<= 1'b0;
            tx_start<=1'b0;
            idx    <= 4'd0;
            guard  <= 1'b0;
            pending<= 1'b0;
            k_sel  <= 2'd0;
        end
        else begin
            tx_start <= 1'b0;
            f_start  <= 1'b0;
            if (res_done) pending <= 1'b1;   // 忙也不会丢

            case (state)
                S_WAIT: if (pending && !m_busy && !fft_act && !wav_act) begin
                            pending<=1'b0;
                            k_sel  <=2'd0;
                            f_start<=1'b1;
                            state  <=S_CF;
                        end
                S_CF:   state <= S_WF;
                S_WF:   if (f_done) begin
                            idx   <= 4'd0;
                            guard <= 1'b0;
                            state <= S_SEND;
                        end
                S_SEND: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx == 4'd14) begin
                            if (k_sel != 2'd2) begin
                                k_sel   <= k_sel + 2'd1;   // SF -> S2 -> S3
                                f_start <= 1'b1;
                                state   <= S_CF;
                            end
                            else state <= S_WAIT;
                        end
                        else begin
                            tx_byte  <= ch;
                            tx_start <= 1'b1;
                            guard    <= 1'b1;
                            idx      <= idx + 4'd1;
                        end
                    end
                end
                default: state <= S_WAIT;
            endcase
        end
    end
endmodule
