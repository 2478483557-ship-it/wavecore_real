//===========================================================================
// 模块名   : fft_demo (v3.3 资源修复版)
// 功能     : FFT 频谱引擎 —— 采样缓存→burst 喂 xfft_0(BFP)→双峰检测
//
// v3.3 (2026-09-30) 【必须保留的修复, 别再改回去】
//   问题: 本模块占全设计 86% 的 LUT 和 93% 的寄存器 —— 17564 LUT / 35558 FF,
//         其中 xfft IP 只占 1771 LUT / 2550 FF, 剩下 15793 LUT / 33008 FF
//         全是它自己"写"出来的。根因是 f_ram 没进块 RAM:
//         f_ram 声明 4096x8 = 32768 bit, 而 33008 - 32768 = 240, 正好等于本模块
//         除数组外所有计数器/状态寄存器之和(手工加总 233) —— 它就是 32768 个 FDRE。
//         4032:1 x 8bit 的读口组合 mux 再吃掉约 8192 LUT6 + 4096 MUXF7 + 2048 MUXF8
//         (实测 MUXF7=4379 / MUXF8=2180, 与估算几乎完全吻合)。
//   证据: 已布线时序报告里直接写着 u_fft_demo/f_ram_reg[3025][5] 是 FDRE;
//         分层资源报告里 u_fft_demo 的 RAMB18=12 = xfft 11 + hann 1, f_ram 贡献 0。
//   为什么推断失败: 旧写法的读口带**异步复位** (if (!rst_n) m_q<=0),
//         Vivado 对 RAM 输出寄存器不支持异步复位 —— 同一条综合日志里
//         uart_mirror 的 fifo_reg 就是这么被 "dissolved into registers" 的。
//         另外旧写法还有两处隐患: f_ram[14'd0] 常量地址读、写口混在主状态机里、
//         地址位宽 14 但数组深度只有 4096。
//   修法: 改成教科书 Simple-Dual-Port 模板 —— 写口独立 always(无复位)、
//         读口独立 always(去异步复位)、地址统一截到 12 位。
//   预期收益: LUT 20829 -> 约 12600 (61%), FF 35818 -> 约 3050 (7%),
//         多用一个 RAMB36(f_ram 32Kb)。布线余量打开后 ILA 也能重新打开。
//   验证口径: 综合后 board_top_utilization_synth.rpt 里 FF 必须掉到 3000 附近;
//         若 FF 仍接近 35818, 说明推断又失败, 请改用 Block Memory Generator IP
//         (见 skill/SK-016: 别赌手写数组的推断)。
//
// v3.2 优化 : 1) f_ram 用块 RAM 的想法(但上面 v3.3 说明当时并未真正生效)
//              2) 第二峰检测改"流式双寄存器法", 去掉 4096 深度幅度缓存
//                 (上一版两块大 reg 数组撑爆 FDRE: 需要 77k, 器件仅 65k)
//              3) Hann 窗 1024 点组合 ROM, N=4096 用 rd_idx[11:2] 查(省 LUT)
// 验证     : 双音 1k+1.1k -> S≈1001, A≈1099 两条稳定谱线
// 作者     : WaveCore 队长 | 日期: 2026-09-30 (v3.3)
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

    //================ 时域缓存(块 RAM, 32768 bit) ================
    // 注意: 这个数组必须是块 RAM。若被综合成触发器, 会直接吃掉 32768 个 FF
    // 外加一个 4096:1 的巨型读 mux —— 详见文件头 v3.3 说明。
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
                ST_CAP: begin                       // 写缓存(写口见上方独立 always)
                    if (decim_cnt == DECIM - 1) begin
                        decim_cnt <= 32'd0;
                        // 写 f_ram 已挪到上方独立 always(必需: 保住块 RAM 推断)
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

    // ---- 写口: 独立 always, 不带复位(带复位会被拒绝推断为 RAM) ----
    // 放在 st 声明之后, 避免"先用后声明"(xvlog 严格模式会报 VRFC 10-3380)
    wire        wr_en_w   = (st == ST_CAP) && (decim_cnt == DECIM - 32'd1);
    wire [11:0] wr_addr_w = wr_idx[11:0];       // 数组深 4096, 地址截到 12 位

    always @(posedge clk)
        if (wr_en_w) f_ram[wr_addr_w] <= ad_cap;

    // ---- 读口: 独立 always, 单条无条件读, **不带异步复位** ----
    // 旧写法 if (!rst_n) m_q<=0 会让 Vivado 拒绝把 f_ram 推断成 RAM
    // (综合日志原话: "RAM is sensitive to asynchronous reset signal.
    //  this RTL style is not supported."), 结果退化成 32768 个 FDRE。
    // m_q 上电为 x 无影响: 复位后要跑满 4096*DECIM 拍才进 ST_CFG, 早就刷成有效值。
    wire        rd_en_w   = (st == ST_CFG && cfg_tready) ||
                            (st == ST_FEED && s_data_tready && rd_idx != NFFT - 1);
    wire [11:0] rd_addr_w = (st == ST_CFG) ? 12'd0 : (rd_idx[11:0] + 12'd1);

    always @(posedge clk)
        if (rd_en_w) m_q <= f_ram[rd_addr_w];

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
                // [09-17 终极修复] 相隔感知的流式双峰(单趟 top-2):
                //   a) 新主峰出现时, 旧主峰仅当与新主峰相隔>2 才降级为第二峰
                //      (否则丢弃: 典型是 Hann 主瓣旁瓣换位, 相似bin不构成"双峰")
                //   b) 常规候选同样要求与当前主峰相隔>2
                //   彻底规避: 主峰晚一拍把自己当候选 / 旁瓣(0.5)顶掉谐波(0.33)
                if (bin_cnt != 14'd0 && bin_cnt <= 14'd2047) begin
                    if (mag > peak_mag) begin
                        if (peak_bin != 14'd0 &&
                            (peak_bin > bin_cnt + 14'd2 || bin_cnt > peak_bin + 14'd2)) begin
                            sec_mag <= peak_mag;   // 旧主峰降级(须相隔>2)
                            sec_bin <= peak_bin;
                        end
                        peak_mag <= mag;           // 新主峰
                        peak_bin <= bin_cnt;
                    end
                    else if (mag > sec_mag &&
                        (bin_cnt > peak_bin + 14'd2 || bin_cnt + 14'd2 < peak_bin)) begin
                        sec_mag <= mag;            // 常规第二峰(须相隔>2)
                        sec_bin <= bin_cnt;
                    end
                end
                if (m_data_tlast) begin
                    fft_hz  <= ((peak_bin * 16'd50000) + 12'd2048) >> 12;
                    fft_done <= 1'b1;
                    // 第二峰门限: 幅度≥主峰1/8 且 相隔>2 (方波3次谐波≈1/3~1/4 稳定通过)
                    if (sec_bin != 14'd0 && sec_mag >= {3'b0, peak_mag[17:3]} &&
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
