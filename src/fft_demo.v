//===========================================================================
// 模块名   : fft_demo (v3.2 资源优化版)
// 功能     : FFT 频谱引擎 —— 采样缓存→burst 喂 xfft_0(BFP)→双峰检测
// v3.2 优化 : 1) f_ram 用块 RAM(ram_style=block), 读写分两个 always 以便推断
//              2) 第二峰检测改"流式双寄存器法", 去掉 4096 深度幅度缓存
//                 (上一版两块大 reg 数组撑爆 FDRE: 需要 77k, 器件仅 65k)
//              3) Hann 窗 1024 点组合 ROM, N=4096 用 rd_idx[11:2] 查(省 LUT)
// 验证     : 双音 1k+1.1k -> S≈1001, A≈1099 两条稳定谱线
// 作者     : WaveCore 队长 | 日期: 2026-09-05
//===========================================================================

module fft_demo #(
    parameter DECIM = 32'd1000,     // fs = 50MHz/1000 = 50kHz
    parameter NFFT  = 16'd4096
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    output reg  [23:0] fft_hz,
    output reg  [23:0] fft_hz2,
    output reg         fft_done,
    output reg         fft_done2
);

    //================ 时域缓存(块 RAM) ================
    (* ram_style = "block" *) reg [7:0] f_ram [0:4095];
    reg [13:0] wr_idx;
    reg [31:0] decim_cnt;

    //================ xfft_0 ================
    reg        cfg_tvalid;
    wire       cfg_tready;
    reg        s_data_tvalid, s_data_tlast;
    reg [31:0] s_data_tdata;
    wire       s_data_tready;
    wire [31:0] m_data_tdata;
    wire       m_data_tvalid, m_data_tlast;

    xfft_0 u_fft (
        .aclk                       (clk            ),
        .s_axis_config_tdata        (8'd0           ),
        .s_axis_config_tvalid       (cfg_tvalid     ),
        .s_axis_config_tready       (cfg_tready     ),
        .s_axis_data_tdata          (s_data_tdata   ),
        .s_axis_data_tvalid         (s_data_tvalid  ),
        .s_axis_data_tready         (s_data_tready  ),
        .s_axis_data_tlast          (s_data_tlast   ),
        .m_axis_data_tdata          (m_data_tdata   ),
        .m_axis_data_tuser          (               ),
        .m_axis_data_tvalid         (m_data_tvalid  ),
        .m_axis_data_tready         (1'b1           ),
        .m_axis_data_tlast          (m_data_tlast   ),
        .m_axis_status_tdata        (               ),
        .m_axis_status_tvalid       (               ),
        .m_axis_status_tready       (1'b1           ),  // SK-014
        .event_frame_started        (               ),
        .event_tlast_unexpected     (               ),
        .event_tlast_missing        (               ),
        .event_status_channel_halt  (               ),
        .event_data_in_channel_halt (               ),
        .event_data_out_channel_halt(               )
    );

    //================ 窗(1024 点组合, >>2 复用于 4096) ================
    reg  [13:0] rd_idx;
    wire [15:0] wq;
    hann_rom u_hann (.clk(clk), .addr(rd_idx[11:2]), .wout(wq));  // 同步块ROM

    //================ 主状态机(写缓存+配置+灌数) ================
    reg [1:0] st;
    localparam ST_CAP=2'd0, ST_CFG=2'd1, ST_FEED=2'd2, ST_WAIT=2'd3;

    reg [7:0] m_q;   // FEED 用的当前样点(独立读 always 产生)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st           <= ST_CAP;
            cfg_tvalid   <= 1'b0;
            s_data_tvalid<= 1'b0;
            s_data_tlast <= 1'b0;
            s_data_tdata <= 32'd0;
            wr_idx       <= 14'd0;
            rd_idx       <= 14'd0;
            decim_cnt    <= 32'd0;
        end
        else begin
            cfg_tvalid    <= 1'b0;
            s_data_tvalid <= 1'b0;
            s_data_tlast  <= 1'b0;
            case (st)
                ST_CAP: begin                       // 写缓存(独立于读)
                    if (decim_cnt == DECIM - 1) begin
                        decim_cnt <= 32'd0;
                        f_ram[wr_idx] <= ad_cap;
                        if (wr_idx == NFFT - 1) begin
                            wr_idx <= 14'd0;
                            rd_idx <= 14'd0;
                            st <= ST_CFG;
                        end
                        else wr_idx <= wr_idx + 14'd1;
                    end
                    else decim_cnt <= decim_cnt + 32'd1;
                end
                ST_CFG: begin
                    cfg_tvalid <= 1'b1;
                    if (cfg_tready) begin
                        st <= ST_FEED;
                        rd_idx <= 14'd0;
                    end
                end
                ST_FEED: begin
                    if (s_data_tready) begin
                        s_data_tvalid <= 1'b1;
                        s_data_tdata  <= {16'd0, win_out};
                        if (rd_idx == NFFT - 1) begin
                            s_data_tlast <= 1'b1;
                            st <= ST_WAIT;
                        end
                        else rd_idx <= rd_idx + 14'd1;
                    end
                end
                ST_WAIT: begin
                    if (m_data_tvalid && m_data_tlast) st <= ST_CAP;
                end
                default: st <= ST_CAP;
            endcase
        end
    end

    // 独立读 always(便于推断 BRAM)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) m_q <= 8'd0;
        else if (st == ST_CFG && cfg_tready) m_q <= f_ram[14'd0];
        else if (st == ST_FEED && s_data_tready && rd_idx != NFFT - 1)
            m_q <= f_ram[rd_idx + 14'd1];
    end

    // 组合换算(读寄存器)
    wire signed [15:0] samp_s = $signed({8'd0, m_q}) - 16'sd128;
    wire signed [31:0] prod   = samp_s * $signed({1'b0, wq});
    wire signed [15:0] win_out = prod[30:15];

    //================ 输出幅度 ================
    wire signed [15:0] re_i = $signed(m_data_tdata[15:0]);
    wire signed [15:0] im_i = $signed(m_data_tdata[31:16]);
    wire [16:0] mag = ((re_i[15] ? (~re_i + 1) : re_i) +
                       (im_i[15] ? (~im_i + 1) : im_i));

    //================ 输出侧: 流式双峰 ================
    reg [13:0] bin_cnt;
    reg [13:0] peak_bin;
    reg [17:0] peak_mag;
    reg [13:0] sec_bin;
    reg [17:0] sec_mag;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bin_cnt  <= 14'd0;
            peak_bin <= 14'd0;
            peak_mag <= 18'd0;
            sec_bin  <= 14'd0;
            sec_mag  <= 18'd0;
            fft_hz   <= 24'd0;
            fft_hz2  <= 24'd0;
            fft_done <= 1'b0;
            fft_done2<= 1'b0;
        end
        else begin
            fft_done  <= 1'b0;
            fft_done2 <= 1'b0;

            if (m_data_tvalid) begin
                // 主峰: 全部有效 bin 中最大(跳过 DC 0 与镜像后半段)
                if (bin_cnt != 14'd0 && bin_cnt <= 14'd2047) begin
                    if (mag > peak_mag) begin
                        peak_mag <= mag;
                        peak_bin <= bin_cnt;
                    end
                end
                // 第二峰候选: 与"当前主峰"相隔>2 的 bin 里取最大
                if (bin_cnt >= 14'd1 && bin_cnt <= 14'd2047) begin
                    if ((bin_cnt > peak_bin + 14'd2 || bin_cnt + 14'd2 < peak_bin) &&
                        mag > sec_mag) begin
                        sec_mag <= mag;
                        sec_bin <= bin_cnt;
                    end
                end
                if (m_data_tlast) begin
                    fft_hz  <= ((peak_bin * 16'd50000) + 12'd2048) >> 12;
                    fft_done <= 1'b1;
                    // 第二峰门限: 幅度≥主峰一半 且 相隔>2
                    if (sec_bin != 14'd0 && sec_mag >= {1'b0, peak_mag[17:1]} &&
                        (sec_bin > peak_bin + 14'd2 || sec_bin + 14'd2 < peak_bin)) begin
                        fft_hz2  <= ((sec_bin * 16'd50000) + 12'd2048) >> 12;
                        fft_done2 <= 1'b1;
                    end
                    bin_cnt  <= 14'd0;
                    peak_bin <= 14'd0;
                    peak_mag <= 18'd0;
                    sec_bin  <= 14'd0;
                    sec_mag  <= 18'd0;
                end
                else begin
                    bin_cnt <= bin_cnt + 14'd1;
                end
            end
        end
    end

endmodule
