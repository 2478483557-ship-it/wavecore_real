//===========================================================================
// 模块名   : wave_id v1.1 (波形自动识别 —— 修正版)
// 原理     : 自适应降采样流 上做两阶段统计(各2048点):
//            阶段0: 跟踪 min/max -> span/mid; 阶段1: 统计 |x-mid| > 3/8*span 占比
//            占比 >0.84 方波 / 0.40~0.62 正弦 / 0.18~0.38 三角 / 其他
// 输入     : ad_cap(与测量同一采集流, 50MHz域)
// 输出     : wave_type: 0=方波 1=正弦 2=三角 3=其他
// 作者     : WaveCore 队长 | 日期: 2026-09-20 | v1.1 修正采样率(关键!)
//===========================================================================
module wave_id (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] ad_cap,
    input  wire [9:0] decim_cfg,   // [10-21] 自适应抽取比 1..1023，由 board_top 按实测频率给出
    output reg  [1:0] wave_type,
    // [10-23] 调试回读用(0x9D): 把判定依据的中间量送出去
    //   dbg_span = 窗口内 max-min（等于 1 倍峰峰值）
    //   dbg_hi   = |x-mid| > 3/8*span 的样点计数（判定就看它）
    output wire [7:0]  dbg_span,
    output wire [12:0] dbg_hi    // [10-24] 12->13 位：窗口已扩到 8192，
                                 //   原来只有 12 位，方波的 hi(=8191) 被截成 4095，
                                 //   导致这段时间所有实测数据都是错的。
);
    // ---- [10-21] 自适应降采样节拍 ----
    // 原来固定 1000（fs=50kHz），导致每周期样点数 spp = 50000/F 随频率下降：
    //   spp=10 时正弦/三角判据区间开始重叠，spp=8 时完全重合（实测 5kHz 就崩）。
    // 现在由 board_top 按实测频率给 decim_cfg，保持 spp ≈ 64~128。
    // 判据推导与实测见 report/wave_id_limit_2026-10-21.md。
    reg  [9:0] dcnt;
    wire [9:0] dec_use = (decim_cfg == 10'd0) ? 10'd1000 : decim_cfg;
    // 用 >= 而不是 ==：decim_cfg 在频率重测时会变，用 >= 不会漏拍
    wire tick = (dcnt >= dec_use - 10'd1);

    // ---- 采样级 3点中值(对降采样点) ----
    reg  [7:0] s0, a1, a2;       // 当前采样点 + 两级历史(均为降采样点)
    wire [7:0] med = ( (s0<a1) ? ((a1<a2)?a1:((s0<a2)?a2:s0))
                               : ((s0<a2)?s0:((a1<a2)?a2:a1)) );

    // ---- 统计状态 ----
    reg  [1:0]  ph;              // 0=测幅 1=计数
    // [10-24] 窗口 2048 -> 8192。
    //   根因：统计窗口若不覆盖整数个周期，mid/span 会随相位漂移。
    //   100kHz、decim=4 时 2048 点 = 16.38 个周期，小数部分导致 hi_cnt
    //   在 956 和 1265 两个簇之间跳（实测），判决随之在"正弦/其他"间摇摆。
    //   放大 4 倍后 8192 点 = 65.5 个周期，小数占比降到 1/4，稳定性显著提高。
    reg  [12:0] cnt;             // 0..8191 (降采样点计数)
    reg  [7:0]  mn, mx, mid, span;
    // [10-23] 回读要用"和判定同一时刻"的值: span/hi_cnt 是实时量,
    //   而 wave_type 是窗口结束才锁存的, 直接读会混两个窗口的数据。
    reg  [7:0]  span_r;
    reg  [12:0] hi_r;   // [10-24] 与 hi_cnt 同宽（13 位）
    reg  [12:0] hi_cnt;
    wire [7:0]  th3 = (span >> 2) + (span >> 3);     // 3/8*span
    wire [8:0]  abs_d = (med > mid) ? (med - mid) : (mid - med);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dcnt<=10'd0; s0<=8'd128; a1<=8'd128; a2<=8'd128;
            ph<=2'd0; cnt<=13'd0; mn<=8'hFF; mx<=8'h00;
            mid<=8'h80; span<=8'h00; hi_cnt<=13'd0; wave_type<=2'd3;
        end
        else begin
            // 节拍发生器
            if (tick) dcnt <= 10'd0;
            else      dcnt <= dcnt + 10'd1;

            if (tick) begin
                s0 <= ad_cap;        // 新样本进入中值链
                a2 <= a1;
                a1 <= s0;            // 注: 流水一节, 无碍统计

                cnt <= (cnt == 13'd8191) ? 13'd0 : (cnt + 13'd1);

                if (cnt == 13'd8191) begin
                    if (ph == 2'd0) begin
                        mid  <= (mn + mx) >> 1;
                        span <= mx - mn;
                        ph   <= 2'd1;
                        hi_cnt <= 13'd0;
                    end
                    else begin
                        span_r <= span;             // [10-23] 与判定同步锁存
                        hi_r   <= hi_cnt;
                        if (span < 8'd16)                       wave_type <= 2'd3;
                        else if (hi_cnt > 13'd6880)             wave_type <= 2'd0;
                        else if (hi_cnt >= 13'd3276 &&
                                 hi_cnt <= 13'd5080)            wave_type <= 2'd1;
                        else if (hi_cnt >= 13'd1476 &&
                                 hi_cnt <= 13'd3112)            wave_type <= 2'd2;
                        else                                    wave_type <= 2'd3;
                        ph <= 2'd0;
                        mn <= 8'hFF; mx <= 8'h00;
                    end
                end
                else begin
                    if (ph == 2'd0) begin
                        // [10-24 关键修复] 这里原来用 s0（原始样本，带毛刺）测 min/max，
                        //   而 phase1 的 hi_cnt 用的是 med（3 点中值滤波后）。
                        //   两者尺度不一致 -> span 在 133/196 之间跳（1.47 倍），
                        //   判据 3/8*span 随之变，hi_cnt 在三角区间和"其他"之间翻。
                        //   实测三角 1kHz 正确率只有 46%，正弦偶尔也掉。
                        //   改成两边都用 med，尺度统一。
                        if (med > mx) mx <= med;
                        if (med < mn) mn <= med;
                    end
                    else begin
                        if (abs_d > th3) hi_cnt <= hi_cnt + 13'd1;
                    end
                end
            end
        end
    end
    // [10-23] 调试回读: 直接引出内部统计量
    assign dbg_span = span_r;
    assign dbg_hi   = hi_r;

endmodule
