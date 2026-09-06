//===========================================================================
// 模块名   : wave_frame (v2.0 直播版)
// 功能     : 波形上传 —— 0x83 请求后"边发边采": 每发 1 字节采一次实时 ad_cap
// 说明     : 字节率=11520B/s, 故等效采样≈11.5kHz, 一帧 1024 点≈90ms 实时波形
//            (90ms 窗口: 200Hz 约18个周期, 1kHz 约90个周期)
//            无内部缓存 -> 不存在 RAM 推断问题(排障结论: RAM版内容恒零)
// 帧格式   : 5A A5 | 01 | 04 | 00 | 1024样点 | SUM
// 作者     : WaveCore 队长 | 日期: 2026-09-06 | 版本: v2.0
//===========================================================================

module wave_frame #(
    parameter NW = 16'd1024
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    input  wire        req,          // 0x83 请求波形(脉冲)
    input  wire        meas_busy,    // 测量行忙
    input  wire        fft_busy,     // 谱峰行忙
    output wire        uart_txd,     // 波形 TX(接引脚 mux)
    output wire        wav_active,   // 1=正在发(引脚 mux 用)
    output wire        wav_hold      // 1=请求未完成(让测量/谱峰暂停)
);

    //================ 串口 ================
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    //================ 状态机 ================
    reg [2:0] st;
    localparam ST_IDLE=3'd0, ST_HOLD=3'd1, ST_HEAD=3'd2, ST_PAY=3'd3,
               ST_TAIL=3'd4, ST_DONE=3'd5;
    reg        req_l;
    reg        wav_act_r;
    reg        guard;
    reg [2:0]  hidx;        // 帧头: 5A A5 01 04 00
    reg [9:0]  pidx;
    reg [7:0]  sum;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st       <= ST_IDLE;
            req_l    <= 1'b0;
            wav_act_r <= 1'b0;
            tx_byte  <= 8'd0;
            tx_start <= 1'b0;
            guard    <= 1'b0;
            hidx     <= 3'd0;
            pidx     <= 10'd0;
            sum      <= 8'd0;
        end
        else begin
            tx_start <= 1'b0;
            if (req) req_l <= 1'b1;

            case (st)
                ST_IDLE: begin
                    if (req_l) st <= ST_HOLD;
                end
                ST_HOLD: begin
                    if (!meas_busy && !fft_busy) begin
                        wav_act_r <= 1'b1;
                        hidx <= 3'd0;
                        pidx <= 10'd0;
                        sum  <= 8'd0;
                        guard <= 1'b0;
                        st   <= ST_HEAD;
                    end
                end
                ST_HEAD: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        case (hidx)
                            3'd0:      tx_byte <= 8'h5A;
                            3'd1:      tx_byte <= 8'hA5;
                            3'd2: begin tx_byte <= 8'h01; sum <= 8'd1; end
                            3'd3: begin tx_byte <= 8'h04; sum <= sum + 8'd4; end
                            default: begin tx_byte <= 8'h00; sum <= sum + 8'd0; end
                        endcase
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        if (hidx == 3'd4) st <= ST_PAY;
                        else hidx <= hidx + 3'd1;
                    end
                end
                ST_PAY: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        tx_byte <= ad_cap;              // 边发边采(实时样点)
                        sum     <= sum + ad_cap;
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        if (pidx == 10'd1023) st <= ST_TAIL;
                        else pidx <= pidx + 10'd1;
                    end
                end
                ST_TAIL: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        tx_byte  <= sum;
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        st       <= ST_DONE;
                    end
                end
                ST_DONE: begin
                    // 等 SUM 完整发完再释放(否则被 mux 切走丢字节)
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        wav_act_r <= 1'b0;
                        req_l     <= 1'b0;
                        st        <= ST_IDLE;
                    end
                end
                default: st <= ST_IDLE;
            endcase
        end
    end

    assign wav_active = wav_act_r;
    assign wav_hold   = req_l;

endmodule
