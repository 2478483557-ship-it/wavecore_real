//===========================================================================
// 模块名   : fft_demo  (v2.1)
// 功能     : P1 FFT 频谱通路 —— 降采样存RAM → 连续burst喂 xfft_0(BFP) → 谱峰
// 流程     : 1) CAPTURE: 每 DECIM(=1000)拍采一次 ad_cap 存入 f_ram(共1024点)
//            2) FEED   : 存储器读入寄存器(m_q)后组合乘窗, 连续推给 xfft
//            3) WAIT   : 等 xfft 输出本帧(tlast) 后回 CAPTURE
// v2.1 修正 : 存储器(reg数组)禁止在连续赋值里读(Verilog-2001) ->
//             改为"always 内读入寄存器, 组合逻辑只用寄存器"
// 验证     : 设 1kHz -> dbg_k 应≈20 ; 500Hz->10 ; 10kHz->205
// 作者     : WaveCore 队长 | 日期: 2026-09-05
//===========================================================================

module fft_demo #(
    parameter DECIM = 32'd1000,     // 采样分频: 50MHz/1000 => fs=50kHz
    parameter NFFT  = 16'd1024
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    output reg  [7:0]  dbg_k,
    output wire [3:0]  dbg_led,    // 调试LED: {cfg_ready,data_ready,st[1:0]}
    output wire [7:0]  dbg_m,      // 调试: {输出有效,帧尾,|re|+|im|高6位}
    output reg  [7:0]  dbg_cnt,    // 调试: 已完成输出帧数(每帧+1, 证明 FFT 活着)
    output reg  [23:0] fft_hz,
    output reg         fft_done
);

    //================ 采样缓存 ================
    reg [7:0] f_ram [0:1023];        // 1024 x 8bit (只允许在 always 里读写)
    reg [9:0] wr_idx;
    reg [31:0] decim_cnt;
    reg [7:0]  m_q;                // FEED 从 f_ram 读出的当前样点(寄存器)

    //================ xfft_0 接口 ================
    reg        cfg_tvalid;
    wire       cfg_tready;
    reg        s_data_tvalid, s_data_tlast;
    reg [31:0] s_data_tdata;
    wire       s_data_tready;
    wire [31:0] m_data_tdata;
    wire       m_data_tvalid, m_data_tlast;

    xfft_0 u_fft (
        .aclk                       (clk          ),
        .s_axis_config_tdata        (8'd0         ),
        .s_axis_config_tvalid       (cfg_tvalid   ),
        .s_axis_config_tready       (cfg_tready   ),
        .s_axis_data_tdata          (s_data_tdata ),
        .s_axis_data_tvalid         (s_data_tvalid),
        .s_axis_data_tready         (s_data_tready),
        .s_axis_data_tlast          (s_data_tlast ),
        .m_axis_data_tdata          (m_data_tdata ),
        .m_axis_data_tuser          (             ),
        .m_axis_data_tvalid         (m_data_tvalid),
        .m_axis_data_tready         (1'b1         ),
        .m_axis_data_tlast          (m_data_tlast ),
        .m_axis_status_tdata        (             ),
        .m_axis_status_tvalid       (             ),
        // BFP 每帧先发状态字(缩放指数), 必须常收丢弃, 否则核心卡住无输出(踩坑)
        .m_axis_status_tready       (1'b1         ),
        .event_frame_started        (             ),
        .event_tlast_unexpected     (             ),
        .event_tlast_missing        (             ),
        .event_status_channel_halt  (             ),
        .event_data_in_channel_halt (             ),
        .event_data_out_channel_halt(             )
    );

    //================ 窗(纯寄存器驱动, 组合无存储器) ================
    reg  [9:0] rd_idx;             // FEED 当前样点序号(与 m_q 对齐)
    wire [15:0] wq;
    hann_rom u_hann (.addr(rd_idx), .wout(wq));

    // 组合换算只读寄存器 m_q 与 wq(合法)
    wire signed [15:0] samp_s = $signed({8'd0, m_q}) - 16'sd128;   // 去直流
    wire signed [31:0] prod   = samp_s * $signed({1'b0, wq});      // x 窗
    wire signed [15:0] win_out = prod[30:15];                      // >>15

    //================ 主状态机 ================
    reg [1:0] st;
    localparam ST_CAP=2'd0, ST_CFG=2'd1, ST_FEED=2'd2, ST_WAIT=2'd3;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st            <= ST_CAP;
            cfg_tvalid    <= 1'b0;
            s_data_tvalid <= 1'b0;
            s_data_tlast  <= 1'b0;
            s_data_tdata  <= 32'd0;
            wr_idx        <= 10'd0;
            rd_idx        <= 10'd0;
            m_q           <= 8'd0;
            decim_cnt     <= 32'd0;
        end
        else begin
            cfg_tvalid    <= 1'b0;
            s_data_tvalid <= 1'b0;
            s_data_tlast  <= 1'b0;

            case (st)
                ST_CAP: begin
                    if (decim_cnt == DECIM - 1) begin
                        decim_cnt <= 32'd0;
                        f_ram[wr_idx] <= ad_cap;
                        if (wr_idx == NFFT - 1) begin
                            wr_idx <= 10'd0;
                            rd_idx <= 10'd0;
                            st     <= ST_CFG;
                        end
                        else begin
                            wr_idx <= wr_idx + 10'd1;
                        end
                    end
                    else begin
                        decim_cnt <= decim_cnt + 32'd1;
                    end
                end

                ST_CFG: begin
                    cfg_tvalid <= 1'b1;
                    if (cfg_tready) begin
                        st     <= ST_FEED;
                        rd_idx <= 10'd0;
                        m_q    <= f_ram[10'd0];      // 预读首点(always 内读存储器合法)
                    end
                end

                ST_FEED: begin
                    if (s_data_tready) begin
                        s_data_tvalid <= 1'b1;
                        s_data_tdata  <= {16'd0, win_out};
                        if (rd_idx == NFFT - 1) begin
                            s_data_tlast <= 1'b1;   // 帧尾
                            st <= ST_WAIT;
                        end
                        else begin
                            rd_idx <= rd_idx + 10'd1;
                            m_q    <= f_ram[rd_idx + 10'd1];   // 预读下一个
                        end
                    end
                end

                ST_WAIT: begin
                    if (m_data_tvalid && m_data_tlast) st <= ST_CAP;
                end
                default: st <= ST_CAP;
            endcase
        end
    end

    //================ 输出侧: 找 |re|+|im| 最大峰 ================
    wire signed [15:0] re_i = $signed(m_data_tdata[15:0]);
    wire signed [15:0] im_i = $signed(m_data_tdata[31:16]);
    wire [16:0] mag = ((re_i[15] ? (~re_i + 1) : re_i) +
                       (im_i[15] ? (~im_i + 1) : im_i));
    assign dbg_m  = {m_data_tvalid, m_data_tlast, mag[16:11]};
    assign dbg_led = {cfg_tready, s_data_tready, st};   // st: 00采集中 01配置 10灌数 11等输出

    reg [9:0]  bin_cnt;
    reg [9:0]  peak_bin;
    reg [17:0] peak_mag;
    reg [7:0]  f_cnt;              // 帧计数(饱和 255)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bin_cnt  <= 10'd0;
            peak_bin <= 10'd0;
            peak_mag <= 18'd0;
            dbg_k    <= 8'd0;
            dbg_cnt  <= 8'd0;
            f_cnt    <= 8'd0;
            fft_hz   <= 24'd0;
            fft_done <= 1'b0;
        end
        else begin
            fft_done <= 1'b0;
            if (m_data_tvalid) begin
                if (bin_cnt != 10'd0 && bin_cnt <= 10'd511) begin
                    if (mag > peak_mag) begin
                        peak_mag <= mag;
                        peak_bin <= bin_cnt;
                    end
                end
                if (m_data_tlast) begin
                    dbg_k   <= peak_bin[7:0];
                    dbg_cnt <= (f_cnt == 8'hFF) ? 8'hFF : (f_cnt + 8'd1);
                    f_cnt   <= (f_cnt == 8'hFF) ? 8'hFF : (f_cnt + 8'd1);
                    fft_hz  <= ((peak_bin * 16'd50000) + 10'd512) >> 10;
                    fft_done <= 1'b1;
                    bin_cnt  <= 10'd0;
                    peak_bin <= 10'd0;
                    peak_mag <= 18'd0;
                end
                else begin
                    bin_cnt <= bin_cnt + 10'd1;
                end
            end
        end
    end

endmodule
