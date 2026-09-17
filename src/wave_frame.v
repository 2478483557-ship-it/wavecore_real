//===========================================================================
// 模块名   : wave_frame (v5.0 · blk_mem_gen IP 缓存版)
// 功能     : 0x83 请求一次, 上传最近 1024 点波形(50kHz = 20.5ms)
// 存储     : 用 Block Memory Generator IP(blk_mem_gen_0, 1024x8 单口RAM)
//           -> RAM 必进 BRAM, 无推断玄学(官方姿势, 替代手写 reg 数组)
// 端口节奏 : 采集时 wea=1 写(addra=wr_idx); 发送时读 douta=mem[addra] 组合直读
// 帧格式   : 5A A5 | 01 | 04 | 00 | 1024样点 | SUM
// 前置     : 先生成 blk_mem_gen_0: Single Port RAM, 1024x8, 无输出寄存器
// 作者     : WaveCore 队长 | 日期: 2026-09-06
//===========================================================================

module wave_frame (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    input  wire        req,
    input  wire [1:0]  trig_mode,   // 0x89: 0=自由 1=上升沿 2=下降沿
    input  wire        meas_busy,
    input  wire        fft_busy,
    output wire        uart_txd,
    output wire        wav_active,
    output wire        wav_hold
);

    //======== blk_mem_gen 接口 ========
    reg  [9:0]  addra_s;
    reg  [7:0]  dina;
    reg         wea;
    wire [7:0]  douta;

    // 单口RAM: 写与读分时复用同一地址口(wea=0 时纯读)
    blk_mem_gen_0 u_bmg (
        .clka  (clk    ),
        .addra (wav_act_r ? addra_s : wr_idx),
        .dina  (dina   ),
        .wea   (wea    ),
        .douta (douta  )
    );

    //======== 采集写入(50kHz) ========
    reg [9:0]  wr_idx;
    reg [31:0] dcnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_idx <= 10'd0;
            dcnt   <= 32'd0;
            wea    <= 1'b0;
            dina   <= 8'd0;
        end
        else if (!wav_act_r) begin
            if (fill_rst) begin
                wr_idx <= 10'd0;               // 触发归零: 帧从触发点开始
                dcnt   <= 32'd0;
            end
            else if (dcnt == 32'd999) begin
                dcnt <= 32'd0;
                wea  <= 1'b1;                 // 写脉冲
                dina <= ad_cap;
                if (wr_idx == 10'd1023) wr_idx <= 10'd0;
                else wr_idx <= wr_idx + 10'd1;
            end
            else begin
                wea <= 1'b0;
                dcnt <= dcnt + 32'd1;
            end
        end
        else wea <= 1'b0;
    end

    //======== 串口 ========
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    //======== 发送状态机 ========
    reg [3:0] st;
    localparam ST_IDLE=4'd0, ST_HOLD=4'd1, ST_HEAD=4'd2, ST_PAY=4'd3,
               ST_TAIL=4'd4, ST_DONE=4'd5, ST_FILL=4'd6;
    reg        req_l;
    reg        wav_act_r;
    reg        guard;
    reg [3:0]  hidx;
    reg [9:0]  cptr;
    reg [9:0]  pidx;
    reg [7:0]  sum;
    reg        fill_seen;
    reg        prev_zero;     // wr_idx 是否刚经过 0
    reg [1:0]  fill_wraps;    // (保留未用)
    reg        fill_rst;      // [触发] 请采集块把写指针归零(单周期脉冲)

    // ---- 触发检测(120/136 迟滞) ----
    reg [7:0] prev_ad;
    wire rise_det = (ad_cap >= 8'd136) && (prev_ad <= 8'd120);
    wire fall_det = (ad_cap <= 8'd120) && (prev_ad >= 8'd136);
    wire trig_ok  = (trig_mode == 2'd0) ? 1'b1 :
                    (trig_mode == 2'd1) ? rise_det : fall_det;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) prev_ad <= 8'd128;
        else        prev_ad <= ad_cap;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st       <= ST_IDLE;
            req_l    <= 1'b0;
            wav_act_r<= 1'b0;
            tx_byte  <= 8'd0;
            tx_start <= 1'b0;
            guard    <= 1'b0;
            hidx     <= 4'd0;
            cptr     <= 10'd0;
            pidx     <= 10'd0;
            sum      <= 8'd0;
            addra_s  <= 10'd0;
            fill_seen<= 1'b0;
            prev_zero<= 1'b1;
            fill_wraps<= 2'd0;
            fill_rst  <= 1'b0;
        end
        else begin
            tx_start <= 1'b0;
            if (req) req_l <= 1'b1;

            case (st)
                ST_IDLE: if (req_l) st <= ST_HOLD;
                ST_HOLD: begin
                    if (!meas_busy && !fft_busy && trig_ok) begin   // 等总线+等触发
                        fill_rst  <= 1'b1;              // 请采集块归零写指针
                        prev_zero <= 1'b1;              // 归零后从 0 开始
                        st        <= ST_FILL;
                    end
                end
                ST_FILL: begin
                    // 归零后写满一整圈(1024 新点) -> 冻结发送; 帧首点=触发点
                    if (fill_rst) begin
                        fill_rst <= 1'b0;          // 单周期脉冲结束
                    end
                    else if (wr_idx == 10'd0) begin
                        if (!prev_zero) begin      // 绕回 0 = 1024 点已写满
                            cptr     <= 10'd0;
                            addra_s  <= 10'd0;
                            hidx     <= 4'd0;
                            pidx     <= 10'd0;
                            sum      <= 8'd0;
                            guard    <= 1'b0;
                            wav_act_r<= 1'b1;
                            st       <= ST_HEAD;
                        end
                        prev_zero <= 1'b1;
                    end
                    else prev_zero <= 1'b0;
                end
                ST_HEAD: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        case (hidx)
                            4'd0:      tx_byte <= 8'h5A;
                            4'd1:      tx_byte <= 8'hA5;
                            4'd2: begin tx_byte <= 8'h01; sum <= 8'd1; end
                            4'd3: begin tx_byte <= 8'h04; sum <= sum + 8'd4; end
                            default: begin tx_byte <= 8'h00; sum <= sum; end
                        endcase
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        if (hidx == 4'd4) st <= ST_PAY;
                        else hidx <= hidx + 4'd1;
                    end
                end
                ST_PAY: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        tx_byte <= douta;        // 组合读: mem[addra_s]
                        sum     <= sum + douta;
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        if (pidx == 10'd1023) st <= ST_TAIL;
                        else begin
                            pidx <= pidx + 10'd1;
                            addra_s <= cptr + pidx + 10'd1;   // 下一地址(自动回绕)
                        end
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
                        st <= ST_DONE;
                    end
                end
                ST_DONE: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        wav_act_r <= 1'b0;
                        req_l     <= 1'b0;
                        st <= ST_IDLE;
                    end
                end
                default: st <= ST_IDLE;
            endcase
        end
    end

    assign wav_active = wav_act_r;
    assign wav_hold   = req_l;
endmodule
