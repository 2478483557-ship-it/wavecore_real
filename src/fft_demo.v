//===========================================================================
// 模块名   : fft_demo (v3.3 资源修复版)
// 功能     : FFT 频谱引擎 -- 采样缓存->burst 喂 xfft_0(BFP)->双峰检测
//
// v3.3 (2026-09-30) 【必须保留的修复, 别再改回去】
//   问题: 本模块占全设计 86% 的 LUT 和 93% 的寄存器 -- 17564 LUT / 35558 FF,
//         其中 xfft IP 只占 1771 LUT / 2550 FF, 剩下 15793 LUT / 33008 FF
//         全是它自己"写"出来的。根因是 f_ram 没进块 RAM:
//         f_ram 声明 4096x8 = 32768 bit, 而 33008 - 32768 = 240, 正好等于本模块
//         除数组外所有计数器/状态寄存器之和(手工加总 233) -- 它就是 32768 个 FDRE。
//         4032:1 x 8bit 的读口组合 mux 再吃掉约 8192 LUT6 + 4096 MUXF7 + 2048 MUXF8
//         (实测 MUXF7=4379 / MUXF8=2180, 与估算几乎完全吻合)。
//   证据: 已布线时序报告里直接写着 u_fft_demo/f_ram_reg[3025][5] 是 FDRE;
//         分层资源报告里 u_fft_demo 的 RAMB18=12 = xfft 11 + hann 1, f_ram 贡献 0。
//   为什么推断失败: 旧写法的读口带**异步复位** (if (!rst_n) m_q<=0),
//         Vivado 对 RAM 输出寄存器不支持异步复位 -- 同一条综合日志里
//         uart_mirror 的 fifo_reg 就是这么被 "dissolved into registers" 的。
//         另外旧写法还有两处隐患: f_ram[14'd0] 常量地址读、写口混在主状态机里、
//         地址位宽 14 但数组深度只有 4096。
//   修法: 改成教科书 Simple-Dual-Port 模板 -- 写口独立 always(无复位)、
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
    input  wire [31:0] decim_cfg,   // [0x8D] 时基抽取比(0 = 用参数 DECIM)
    input  wire [31:0] fs_cfg,      // [0x8D] 等效采样率 Hz(0 = 用 50000)
    output reg  [23:0] fft_hz,
    output reg  [23:0] fft_hz2,
    output reg         fft_done,
    output reg         fft_done2,
    // [10-24] 0x9F 调试回读: {st, cfg_tready, s_data_tready, m_data_tvalid}
    output wire [7:0]  dbg_st,
    output wire [23:0] dbg_idx
);

    //======== [0x8D] 时基: 外部配置优先, 未接(0)时回退参数 ========
    wire [31:0] decim_use = (decim_cfg == 32'd0) ? DECIM    : decim_cfg;
    wire [31:0] fs_use    = (fs_cfg    == 32'd0) ? 32'd50000 : fs_cfg;

    //================ 时域缓存(块 RAM, 32768 bit) ================
    // 注意: 这个数组必须是块 RAM。若被综合成触发器, 会直接吃掉 32768 个 FF
    // 外加一个 4096:1 的巨型读 mux -- 详见文件头 v3.3 说明。
    (* ram_style = "block" *) reg [7:0] f_ram [0:4095];
    reg [13:0] wr_idx;
    reg [31:0] decim_cnt;

    // [10-24] 状态声明上移：m_axis_data_tready 在例化里就要引用 ST_WAIT，
    //   留在下面会被当成隐式 1 位 wire，或直接报 "already declared"。
    reg [1:0] st;
    localparam ST_CAP=2'd0, ST_CFG=2'd1, ST_FEED=2'd2, ST_WAIT=2'd3;

    //================ xfft_0 ================
    reg        cfg_tvalid;
    wire       cfg_tready;
    // [10-24 关键修复] 三个信号改成**组合**驱动。
    //   PG109 明确要求 s_axis_data_tready 必须被遵守，且它可能在一帧中途拉低。
    //   原来 tvalid/tdata/tlast 是寄存器，比 tready 晚一拍：
    //     第 N 拍看到 tready=1 就认为已发出并推进 rd_idx，
    //     真正握手发生在第 N+1 拍；那拍 tready 若变低，这个点就丢了。
    //   丢的若是最后一个点，tlast 随之丢失 -> IP 永不输出 ->
    //     m_data_tlast 不来 -> 卡死在 ST_WAIT（实测 decim=8 时 p_s 恒 0）。
    //   decim 大时数据慢、tready 恒高，碰巧不出问题，所以这个 bug 潜伏很久。
    wire        s_data_tvalid;
    wire        s_data_tlast;
    wire [31:0] s_data_tdata;
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
        // [10-24 关键修复] 原来接死 1'b1，IP 的输出被"无声吞掉"——
        //   包括 tlast。状态机在 ST_CAP 期间不处理输出，tlast 就这么丢了，
        //   fft_done 永不产生（0x9E 实测 p_s 恒 0）。
        //   改为由状态机控制：只在 ST_WAIT 收输出，其余时间让它堵住。
        //   这是 AXI-Stream 消费者该做的事，PG109 也要求遵守 tready。
        .m_axis_data_tready         (st == ST_WAIT  ),
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
    // (st 与 localparam 已上移到 xfft_0 例化之前)

    reg [7:0] m_q;   // FEED 用的当前样点(独立读 always 产生)
    // [10-19 修复] 下面三个 wire 原来声明在 180 行之后，但 146 行（ST_FEED）就要用 win_out。
    //   Verilog-2001 会隐式声明成 1 位 wire -- {16'd0, win_out} 就只有 17 位，
    //   送进 32 位 FFT 输入时高位补零，等于只有 1 个比特有效。
    //   Vivado 恰好取了后面的显式声明所以实测正常，但这是运气，不是设计。
    wire signed [15:0] samp_s;
    wire signed [31:0] prod;
    wire signed [15:0] win_out;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st           <= ST_CAP;
            cfg_tvalid   <= 1'b0;
            wr_idx       <= 14'd0;
            rd_idx       <= 14'd0;
            decim_cnt    <= 32'd0;
        end
        else begin
            cfg_tvalid    <= 1'b0;
            case (st)
                ST_CAP: begin                       // 写缓存(写口见上方独立 always)
                    if (decim_cnt == decim_use - 32'd1) begin
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
                    // tvalid 恒高（组合），因此这里的条件等价于"握手成功"
                    if (s_data_tready) begin
                        if (rd_idx == NFFT - 1) st     <= ST_WAIT;
                        else                     rd_idx <= rd_idx + 14'd1;
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
    wire        wr_en_w   = (st == ST_CAP) && (decim_cnt == decim_use - 32'd1);
    wire [11:0] wr_addr_w = wr_idx[11:0];       // 数组深 4096, 地址截到 12 位

    always @(posedge clk)
        if (wr_en_w) f_ram[wr_addr_w] <= ad_cap;

    // [10-24] AXI-Stream 主机侧：tvalid 在 ST_FEED 期间恒高，
    //   只有 tvalid && tready 同拍为高才算传输成功；tlast 与最后一点严格对齐。
    assign s_data_tvalid = (st == ST_FEED);
    assign s_data_tlast  = (st == ST_FEED) && (rd_idx == NFFT - 1);
    assign s_data_tdata  = {16'd0, win_out};

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

    // 组合换算(读寄存器) -- 声明已前置到模块上方（见 10-19 修复注释）
    assign samp_s  = $signed({8'd0, m_q}) - 16'sd128;
    assign prod    = samp_s * $signed({1'b0, wq});
    assign win_out = prod[30:15];

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
                    // [09-30 深夜 BUGFIX] 原来写 16'd50000 / 12'd2048 -- 按 Verilog 位宽规则
                    //   该式被提升到左值 fft_hz 的 24 位, 于是 bin>=336 (4101Hz) 起静默溢出,
                    //   读数恰好偏 -16384Hz。改成 32 位后 4095*50000=204,750,000 不再溢出。
                    //   证据: hw_analysis/check_self_fft_overflow.py
                    fft_hz  <= (({32'd0, peak_bin} * fs_use) + 44'd2048) >> 12;   // [10-23] 显式加宽, 防高频溢出
                    fft_done <= 1'b1;
                    // 第二峰门限: 幅度>=主峰1/8 且 相隔>2 (方波3次谐波≈1/3~1/4 稳定通过)
                    if (sec_bin != 14'd0 && sec_mag >= {3'b0, peak_mag[17:3]} &&
                        (sec_bin > peak_bin + 14'd2 || sec_bin + 14'd2 < peak_bin)) begin
                        // [09-30 深夜 BUGFIX] 同上, 32 位防溢出
                        fft_hz2  <= (({32'd0, sec_bin} * fs_use) + 44'd2048) >> 12;
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

    // [10-24] 调试回读
    assign dbg_st  = {st, cfg_tready, s_data_tready, m_data_tvalid, 1'b0};
    assign dbg_idx = {wr_idx, rd_idx[9:0]};

endmodule
