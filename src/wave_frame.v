//===========================================================================
// 模块名   : wave_frame (v6.0 · blk_mem_gen IP 缓存版 + [0x8F] 预触发)
// 功能     : 0x83 请求一次, 上传最近 1024 点波形(默认 50kHz = 20.5ms; [0x8D] 时基可改)
// [v6.0 新增 0x8F 预触发] 可选触发点在帧内的位置: 0% / 25% / 50% / 75%
//            - 采集改为**永不归零的环形缓冲**(一直写 1024 深)
//            - 触发瞬间锁存写指针 trig_wptr, 再写 (1024-pre_n) 点后冻结
//            - 发送起点 cptr = trig_wptr - pre_n  -> 帧内第 pre_n 点就是触发点
//            - **pre_n = 0 时行为与 v5.0 等价**(帧首点 = 触发后第一个采样点)
// 验收     : 设 50% 预触发请求波形 -> 图上能看到触发边沿左侧的半个波形,
//            且触发点位于帧正中(第 512 个点)
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
    input  wire [31:0] decim_cfg,   // [0x8D] 时基抽取比(0 = 用 1000 默认)
    input  wire        req,
    input  wire [1:0]  trig_mode,   // 0x89: 0=自由 1=上升沿 2=下降沿
    input  wire [1:0]  pre_cfg,     // [0x8F] 预触发档: 0=0% 1=25% 2=50% 3=75%
    input  wire        meas_busy,
    input  wire        fft_busy,
    output wire        uart_txd,
    output wire        wav_active,
    output wire        wav_hold
);

    // [0x8D] 时基: 波形抽取比(默认 1000 -> 50kHz; T2=4000 -> 12.5kHz; T3=500 -> 100kHz)
    wire [31:0] decim_use = (decim_cfg == 32'd0) ? 32'd1000 : decim_cfg;

    //======== blk_mem_gen 接口 ========
    reg  [9:0]  addra_s;
    reg  [7:0]  dina;
    reg         wea;
    wire [7:0]  douta;

    // ---- [v6.0] 前置声明(必须先声明后使用) ----
    //   下面 blk_mem_gen_0 的 .addra() 端口里直接用到了 wr_idx / wav_act_r,
    //   若把声明留在例化之后, xvlog 会报 VRFC 10-2938 "already implicitly declared"
    //   -- 即它们先被当成 **1 位隐式网**, 与 board_top.v 曾经修过的隐式线网是同一类坑。
    reg [9:0]  wr_idx;      // 采集写指针(1024 深环形)
    reg [31:0] dcnt;        // 抽取分频计数
    reg        wav_act_r;   // 1 = 正在发送(此期间不写 RAM, 地址口归读)

    // 单口RAM: 写与读分时复用同一地址口(wea=0 时纯读)
    blk_mem_gen_0 u_bmg (
        .clka  (clk    ),
        .addra (wav_act_r ? addra_s : wr_idx),
        .dina  (dina   ),
        .wea   (wea    ),
        .douta (douta  )
    );

    //======== 采集写入(50kHz) ========
    // (wr_idx / dcnt 的声明已上移到 blk_mem_gen_0 例化之前, 见上)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_idx <= 10'd0;
            dcnt   <= 32'd0;
            wea    <= 1'b0;
            dina   <= 8'd0;
        end
        else if (!wav_act_r) begin
            // [v6.0] 原"触发时归零写指针"的分支已删除 -> 采集永远是环形常写,
            //   预触发所需的历史数据就靠"不归零"保留在缓冲里。
            if (dcnt == decim_use - 32'd1) begin
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
    // (wav_act_r 的声明已上移到 blk_mem_gen_0 例化之前, 见上)
    reg        guard;
    // [10-23] 看门狗: 卡在 HOLD/FILL 超过 ~335ms(50MHz) 就放弃本次请求。
    //   原来没有超时，一旦触发条件不满足就永久挂住，并拉高 wav_hold
    //   把测量一起冻死 -- 实机表现为整块板子静默，只能重新配置 FPGA。
    reg [23:0] wdog;
    reg [3:0]  hidx;
    reg [9:0]  cptr;
    reg [9:0]  pidx;
    reg [7:0]  sum;
    reg        fill_seen;     // (保留未用)
    // [v6.0 预触发] 不再"归零写指针", 改为锁存触发位置 + 按点数冻结
    reg [9:0]  trig_wptr;     // 触发瞬间的写指针(= 触发后第一个采样点的地址)
    reg [9:0]  fill_cnt;      // 触发后已写入的采样点数
    // 预触发点数: 0 / 256 / 512 / 768 (即 0% / 25% / 50% / 75%)
    wire [9:0] pre_n = (pre_cfg == 2'd1) ? 10'd256 :
                       (pre_cfg == 2'd2) ? 10'd512 :
                       (pre_cfg == 2'd3) ? 10'd768 : 10'd0;

    // ---- 触发检测(120/136 迟滞) ----
    // [v6.1 修复"慢边沿漏触发"] 原实现要求"相邻两拍"完成跨阈(<=120 -> >=136)，
    //   平缓边沿永远无法满足：1kHz 正弦在 fs=50kHz 下每拍仅变化约 3.5 个码(需 16 个)，
    //   实测"正弦完全收不到波形、方波正常"。
    //   改为状态位：先"蓄势"(回到本侧电位)，再越过对侧阈值即触发；触发后自动解除。
    //   陡边沿下与原版行为等价(仍为单拍脉冲)。
    reg armed_lo;   // 曾到低电位(<=120) -> 允许上升沿触发
    reg armed_hi;   // 曾到高电位(>=136) -> 允许下降沿触发
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            armed_lo <= 1'b1;          // 上电默认允许上升沿触发
            armed_hi <= 1'b0;
        end
        else if (ad_cap <= 8'd120) begin
            armed_lo <= 1'b1;  armed_hi <= 1'b0;
        end
        else if (ad_cap >= 8'd136) begin
            armed_hi <= 1'b1;  armed_lo <= 1'b0;
        end
    end
    wire rise_det = armed_lo && (ad_cap >= 8'd136);
    wire fall_det = armed_hi && (ad_cap <= 8'd120);
    wire trig_ok  = (trig_mode == 2'd0) ? 1'b1 :
                    (trig_mode == 2'd1) ? rise_det : fall_det;

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
            trig_wptr<= 10'd0;
            fill_cnt <= 10'd0;
        end
        else begin
            tx_start <= 1'b0;
            if (req) req_l <= 1'b1;

            case (st)
                ST_IDLE: begin
                    wdog <= 24'd0;
                    // [10-23] 高频档(decim < 100)不支持波形帧:
                    //   该路径在极小 decim 下采集永远凑不满, 会一路残留忙态,
                    //   实测连累之后的 T1 请求也失败。这里直接拒绝, 让上层超时即可。
                    //   频谱(0x8A/0x8E)不受影响, T3/T4 本来就是给频谱用的。
                    if (req_l && (decim_use >= 32'd100)) st <= ST_HOLD;
                    else if (req_l)                      req_l <= 1'b0;
                end
                ST_HOLD: begin
                    // [10-23] 不再等 meas_busy: 高频档下测量模块几乎一直忙,
                    //   结果是波形请求永远进不去、每帧都靠看门狗超时放弃。
                    //   波形采集只是读 ad_cap, 与测量并不冲突; 发送冲突由 TX 仲裁解决。
                    if (!fft_busy && trig_ok) begin   // 只避让谱帧, 并等触发
                        trig_wptr <= wr_idx;      // [v6.0] 锁存触发位置(不再归零)
                        fill_cnt  <= 10'd0;
                        wdog      <= 24'd0;
                        st        <= ST_FILL;
                    end
                    else if (wdog == 24'hFFFFFF) begin                // [10-23] 超时放弃
                        // 必须同时撤掉 req_l: wav_hold = req_l, 不清就会立刻重进 HOLD,
                        // 变成活锁, 而且测量被永久暂停(实机看着像整块板子死了)
                        req_l <= 1'b0;
                        st    <= ST_IDLE;
                    end
                    else wdog <= wdog + 24'd1;
                end
                ST_FILL: begin
                    // [v6.0] 触发后再写 (1024-pre_n) 个采样点就冻结;
                    //   加上缓冲里原有的 pre_n 点历史, 合计正好覆盖 1024 点。
                    if (wea) begin                      // 每个写脉冲 = 一个新采样点
                        if (fill_cnt == (10'd1023 - pre_n)) begin
                            // 发送起点回退 pre_n 点 -> 帧内第 pre_n 点 = 触发点
                            cptr      <= trig_wptr - pre_n;
                            addra_s   <= trig_wptr - pre_n;
                            hidx      <= 4'd0;
                            pidx      <= 10'd0;
                            sum       <= 8'd0;
                            guard     <= 1'b0;
                            wav_act_r <= 1'b1;
                            st        <= ST_HEAD;
                        end
                        else fill_cnt <= fill_cnt + 10'd1;
                    end
                    else if (wdog == 24'hFFFFFF) begin                // [10-23] 超时放弃
                        // 必须同时撤掉 req_l: wav_hold = req_l, 不清就会立刻重进 HOLD,
                        // 变成活锁, 而且测量被永久暂停(实机看着像整块板子死了)
                        req_l <= 1'b0;
                        st    <= ST_IDLE;
                    end
                    else wdog <= wdog + 24'd1;
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
