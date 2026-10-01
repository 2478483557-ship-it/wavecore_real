//===========================================================================
// 模块名   : spec_frame  (0x8E 幅度谱帧发送, v1.0)
// 功能     : 收到 0x8E -> 先等自研FFT空闲 -> 触发一次采集 -> 完成后发送
//            512 点幅度谱帧(对数压缩, 8bit/点)
// 帧格式   : 5A A5 | 02 | 02 00 | 512 字节 | SUM   (= 518 字节)
//            SUM = (02 + 02 + 00 + 全部数据字节) 求和取低 8 位
//            460800-8N1 下约 11.2ms / 帧, 理论 89 帧/s
// 仲裁     : 与 wave_frame 同构 ——
//            请求期间 hold=1(暂停测量/谱峰等其它行);
//            fft_run 前先等 sf_busy=0(避免触发落到上一轮运行中间, 结果错位);
//            发送前再等 meas/fft/wav/sf 各路都空闲, 防止把别人截断。
// 对应模型 : hw_analysis/verify_spectrum_frame.py(逐字节金标准)
// 作者     : WaveCore 队长 | 2026-09-30 | v1.0
//===========================================================================
module spec_frame (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        req,          // 0x8E 请求(1 拍脉冲)
    input  wire        sf_busy,      // 自研FFT 正在运行(等它空闲再触发, 防错位)
    input  wire        fft_done,     // 自研FFT res_done(本轮完成脉冲)
    input  wire        meas_busy,    // 测量行忙
    input  wire        fft_busy,     // IP 谱峰行忙
    input  wire        wav_busy,     // 波形帧忙
    input  wire        sf_line_busy, // 自研FFT 行(SF=)上报忙
    output reg         fft_run,      // -> self_fft_1024 的 run
    input  wire [7:0]  rdata,        // spec_buf 读出(异步读, 组合有效)
    output wire [8:0]  raddr,        // spec_buf 读地址
    output wire        uart_txd,
    output wire        spec_active,  // 占用 TX 标志
    output wire        spec_hold     // 请求期间暂停其它行(=req_l)
);

    // ---- 串口(与 wave_frame 同款用法) ----
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    // ---- 状态机 ----
    localparam ST_IDLE = 3'd0,
               ST_WAIT = 3'd1,   // 等自研FFT 完成
               ST_PRE  = 3'd2,   // 等各路空闲
               ST_HEAD = 3'd3,   // 帧头 5 字节
               ST_PAY  = 3'd4,   // 512 数据
               ST_TAIL = 3'd5,   // SUM
               ST_DONE = 3'd6;
    reg [2:0]  st;
    reg        want;        // 请求登记(等 sf_busy 期间不丢)
    reg        req_l;       // 请求锁存 = hold
    reg        act_r;       // 发送占用
    reg        guard;
    reg [2:0]  hidx;
    reg [8:0]  pidx;
    reg [15:0] sum16;       // 16 位累加, 发送前取低 8 位(512 个 0xFF 也不会溢出)
    reg [8:0]  raddr_r;
    reg [24:0] wd_cnt;      // [看门狗] ST_WAIT 计时: bit24=1 约 **335.5ms**
                            // [10-01 修] 原 bit21 = 41.9ms, 是按 T1(decim=1000, 一轮 20.5ms) 定的;
                            //   但时基 T2(decim=4000) 下一轮要 1024x4000/50MHz = **81.9ms**,
                            //   看门狗会提前超时 -> 释放 hold 回 IDLE -> **谱帧永远发不出去**
                            //   (症状: T2 时瀑布图/频谱整片空白, T1/T3 正常)。
                            //   改 335ms: 对 T2 的 83ms 有 4 倍余量, 又仍能兜住"真卡死"。
                            //   ★ 教训: 改"时间尺度"类参数(时基/抽取比)时, 所有**固定超时**都要一起审。
                            // 正常一次运行约 22ms; 若真超时则释放 hold 回 IDLE,
                            // 绝不把测量流卡死成"必须按复位"。这是安全网, 正常情况下永远不触发。

    assign raddr       = raddr_r;
    assign spec_active = act_r;
    assign spec_hold   = req_l;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st      <= ST_IDLE;
            want    <= 1'b0;
            req_l   <= 1'b0;
            act_r   <= 1'b0;
            tx_byte <= 8'd0;
            tx_start<= 1'b0;
            guard   <= 1'b0;
            hidx    <= 3'd0;
            pidx    <= 9'd0;
            sum16   <= 16'd0;
            raddr_r <= 9'd0;
            fft_run <= 1'b0;
            wd_cnt  <= 25'd0;
        end
        else begin
            tx_start <= 1'b0;
            fft_run  <= 1'b0;

            case (st)
                ST_IDLE: begin
                    if (want && !sf_busy) begin
                        want    <= 1'b0;
                        req_l   <= 1'b1;          // 从这里开始 hold
                        fft_run <= 1'b1;          // 触发一次自研FFT
                        wd_cnt  <= 25'd0;         // [看门狗] 归零
                        st      <= ST_WAIT;
                    end
                    else if (req) begin
                        want <= 1'b1;
                    end
                end
                ST_WAIT: begin
                    wd_cnt <= wd_cnt + 25'd1;
                    if (fft_done) begin
                        st <= ST_PRE;                      // 本轮完成
                    end
                    else if (wd_cnt[24]) begin             // [看门狗] ~335ms 超时(T2 的 83ms 也够)
                        req_l <= 1'b0;                     // 释放 hold, 不卡测量流
                        st    <= ST_IDLE;
                    end
                end
                ST_PRE: begin
                    if (!meas_busy && !fft_busy && !wav_busy && !sf_line_busy) begin
                        raddr_r <= 9'd0;          // 读地址归零
                        hidx    <= 3'd0;
                        pidx    <= 9'd0;
                        sum16   <= 16'd0;
                        guard   <= 1'b0;
                        act_r   <= 1'b1;          // 开始占用 TX
                        st      <= ST_HEAD;
                    end
                end
                ST_HEAD: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        case (hidx)
                            3'd0:    tx_byte <= 8'h5A;                    // 帧头1
                            3'd1:    tx_byte <= 8'hA5;                    // 帧头2
                            3'd2: begin tx_byte <= 8'h02; sum16 <= 16'h0002; end  // TYPE
                            3'd3: begin tx_byte <= 8'h02; sum16 <= sum16 + 16'h0002; end // LEN_H
                            default: tx_byte <= 8'h00;                    // LEN_L(不加和)
                        endcase
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        if (hidx == 3'd4) st <= ST_PAY;
                        else              hidx <= hidx + 3'd1;
                    end
                end
                ST_PAY: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        tx_byte <= rdata;                       // 异步读: mem[raddr_r]
                        sum16   <= sum16 + {8'd0, rdata};
                        tx_start<= 1'b1;
                        guard   <= 1'b1;
                        if (pidx == 9'd511) st <= ST_TAIL;
                        else begin
                            pidx    <= pidx + 9'd1;
                            raddr_r <= pidx + 9'd1;             // 预取下一地址
                        end
                    end
                end
                ST_TAIL: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        tx_byte  <= sum16[7:0];
                        tx_start <= 1'b1;
                        guard    <= 1'b1;
                        st       <= ST_DONE;
                    end
                end
                ST_DONE: begin
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        act_r <= 1'b0;
                        req_l <= 1'b0;
                        st    <= ST_IDLE;
                    end
                end
                default: st <= ST_IDLE;
            endcase
        end
    end
endmodule
