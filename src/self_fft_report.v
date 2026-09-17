//===========================================================================
// 模块名   : self_fft_report  (自研FFT结果上报: "SF=xxxxxxxHz\r\n")
// 时序     : 等总线全闲(!m_busy & !fft_act & !wav_act)才开始, 发完释放
// 作者     : WaveCore 队长 | 2026-09-16 | v1.0
//===========================================================================
module self_fft_report (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [23:0] res_freq,
    input  wire        res_done,
    input  wire        m_busy,      // 测量行忙
    input  wire        fft_act,     // 谱峰行忙
    input  wire        wav_act,     // 波形帧忙
    input  wire [3:0]  core_st,     // [调试] 自研FFT核心状态
    output wire        uart_txd,
    output wire        sf_active    // 本模块占用TX(供外部让路/引脚仲裁)
);
    // ---- 频率 BCD ----
    wire [27:0] f_bcd; wire f_done; reg f_start;
    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2f (
        .clk(clk), .rst_n(rst_n), .start(f_start),
        .bin(res_freq), .bcd(f_bcd), .done(f_done) );

    function [3:0] d10(input [27:0] v, input [3:0] idx);
        d10 = v[idx*4 +: 4];
    endfunction

    reg [7:0] tx_byte; reg tx_start; wire tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));
    // "SF=" + 7digits + "Hz\r\n" = 14 字节
    reg [3:0] idx;
    wire [7:0] ch = char_at(idx);
    function [7:0] char_at(input [3:0] i);
        case (i)
            4'd0: char_at = 8'h53;                        // 'S'
            4'd1: char_at = 8'h46;                        // 'F'
            4'd2: char_at = 8'h3D;                        // '='
            4'd3: char_at = 8'd48 + d10(f_bcd, 3'd6);
            4'd4: char_at = 8'd48 + d10(f_bcd, 3'd5);
            4'd5: char_at = 8'd48 + d10(f_bcd, 3'd4);
            4'd6: char_at = 8'd48 + d10(f_bcd, 3'd3);
            4'd7: char_at = 8'd48 + d10(f_bcd, 3'd2);
            4'd8: char_at = 8'd48 + d10(f_bcd, 3'd1);
            4'd9: char_at = 8'd48 + d10(f_bcd, 3'd0);
            4'd10:char_at = 8'h48;                        // 'H'
            4'd11:char_at = 8'h7A;                        // 'z'
            4'd12:char_at = 8'h0D;
            default: char_at = 8'h0A;                     // 13 = LF
        endcase
    endfunction

    localparam S_WAIT=2'd0, S_CF=2'd1, S_WF=2'd2, S_SEND=2'd3;
    reg [1:0] state; reg guard;
    reg       pending;      // 结果待发(总线忙也不会丢)
    reg [24:0] hb;          // [临时] 心跳计数器(0.25s)
    reg        hb_act;      // 心跳占用TX标志
    reg        hb_seen;     // 已看到uart忙
    reg        hb_par;      // 0=发Z, 1=发状态hex(交替)
    function [7:0] hx(input [3:0] v);
        hx = (v < 4'd10) ? (8'd48 + v) : (8'd55 + v);
    endfunction
    assign sf_active = (state != S_WAIT) || hb_act;

    // 结果锁存: res_done 不管总线忙不忙都先记住
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) pending <= 1'b0;
        else if (res_done) pending <= 1'b1;
        else if (state == S_WAIT && pending && !m_busy && !fft_act && !wav_act)
            pending <= 1'b0;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=S_WAIT; f_start<=0; tx_start<=0; idx<=0; guard<=0;
            hb<=25'd0; hb_act<=1'b0; hb_seen<=1'b0; hb_par<=1'b0;
        end
        else begin
            tx_start<=1'b0; f_start<=1'b0;
            // [临时] 每0.25s: 交替发 'Z'(存活) 与 核心状态hex(卡点定位)
            if (hb == 25'd12_499_999) begin
                hb <= 25'd0;
                if (state==S_WAIT && !hb_act && !m_busy && !fft_act && !wav_act) begin
                    tx_byte  <= hb_par ? hx(core_st) : 8'h5A;
                    hb_par   <= ~hb_par;
                    tx_start <= 1'b1;
                    hb_act   <= 1'b1;
                    hb_seen  <= 1'b1;
                end
            end
            else hb <= hb + 25'd1;
            // 心跳占用释放: 先看到忙, 忙结束后释放
            if (hb_seen && tx_busy) hb_seen <= 1'b0;
            else if (hb_act && !hb_seen && !tx_busy) hb_act <= 1'b0;
            case (state)
                S_WAIT: if (pending && !m_busy && !fft_act && !wav_act) begin
                            f_start<=1'b1; state<=S_CF;
                        end
                S_CF: state<=S_WF;
                S_WF: if (f_done) begin idx<=4'd0; guard<=1'b0; state<=S_SEND; end
                S_SEND: begin
                    if (guard) begin
                        if (tx_busy) guard<=1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx==4'd14) state<=S_WAIT;
                        else begin
                            tx_byte<=ch; tx_start<=1'b1; guard<=1'b1;
                            idx<=idx+4'd1;
                        end
                    end
                end
                default: state<=S_WAIT;
            endcase
        end
    end
endmodule
