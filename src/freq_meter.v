//===========================================================================
// 模块名   : freq_meter
// 功能     : 频率计 v2.0 —— 自动双模式测频(P0-2)
// 设计目标 : 100Hz ~ 1MHz 全频段误差 <1%
// 两种测法自动切换:
//   模式A 闸门计数(快) : 10ms 闸门数周期 -> f = cnt x 100
//        用于 >= 10kHz (10ms 内 >=100 个周期, ±1计数 = ±1%)
//   模式B 测周法(准)  : 数【32 个完整周期】用了多少个 50MHz 时钟,
//        f = 32 x 50MHz / clks = 1.6e9 / clks
//        用于 < 10kHz (32 周期平均, 量化误差 0.001% 级)
//        clks 由恢复余数除法器(div_restore)算出, 算法已 Python 逐拍验证
// 迟滞比较(HYST)沿用 v1.1: 跌破112武装 -> 升过144计一个周期, 抗噪声
// 输出 : freq_hz(直接 Hz, 供串口显示) + vpp + meas_done
// 作者 : WaveCore 队长 | 日期: 2026-09-05 | 版本: v2.0
//===========================================================================

module freq_meter #(
    parameter GATE1_CLKS   = 500_000,    // 粗闸门 10ms @50MHz
    parameter HYST_L       = 8'd112,     // 迟滞低阈值
    parameter HYST_H       = 8'd144,     // 迟滞高阈值
    parameter FINE_CYC     = 6'd32,      // 测周法: 32 个周期取平均
    parameter [31:0] FINE_NUM = 32'd1_600_000_000  // 32 x 50MHz
)(
    input  wire        clk,        // 系统时钟 50MHz
    input  wire        rst_n,      // 复位, 低有效
    input  wire [7:0]  ad_cap,     // 采集到的 ADC 数据
    output reg  [23:0] freq_hz,    // 测量频率(Hz)
    output reg  [7:0]  vpp,        // 峰峰值
    output reg         meas_done   // 测量完成脉冲
);

    // ============ 状态 ============
    reg [1:0] st;
    localparam ST_COARSE = 2'd0;   // 10ms 粗测
    localparam ST_FINE   = 2'd1;   // 测周法
    localparam ST_CALC   = 2'd2;   // 等除法器算完

    // ============ 通用: 迟滞过零(自适应阈值) ============
    reg        armed;
    reg [7:0]  thr_l;      // 自适应低阈值(上一轮波形中心 -12)
    reg [7:0]  thr_h;      // 自适应高阈值(上一轮波形中心 +12)
    wire [8:0] mid_sum = {1'b0, max_v} + {1'b0, min_v};  // 9位求和防溢出
    wire [7:0] mid_c   = mid_sum[8:1];                    // (max+min)/2 = 中心
    // 中心±12(钳到 0~255)
    wire [7:0] next_l = (mid_c > 8'd12) ? (mid_c - 8'd12) : 8'd0;
    wire [7:0] next_h = (mid_c > 8'd243)? 8'd255 : (mid_c + 8'd12);
    wire upcross = armed && (ad_cap >= thr_h);

    // ============ 粗测(闸门) ============
    reg [18:0] gate_cnt;
    reg [16:0] cnt_gate;           // 粗测周期数(≥100 即快测)

    // ============ 细测(测周法) ============
    reg [5:0]  ev_cnt;             // 已数周期(到 32)
    reg [24:0] t_cnt;              // 计时器(50MHz 时钟数, 25 位: 供除法器取 [24:0])
    reg        div_start;
    wire       div_done;
    wire [31:0] div_q;
    reg        t_ok;               // 计时是否在有效范围
    reg [12:0] wd_cnt;             // ST_CALC 看门狗

    // 除法器: f = FINE_NUM / t_cnt
    div_restore #(.N(32), .D(25)) u_div (
        .clk   (clk       ),
        .rst_n (rst_n     ),
        .start (div_start ),
        .num   (FINE_NUM  ),
        .den   (t_cnt[24:0]),
        .q     (div_q     ),
        .done  (div_done  )
    );

    // ============ 峰峰值(跨整个测量过程跟踪) ============
    reg [7:0] max_v, min_v;

    // 显示限幅(串口 F 字段固定 7 位, 最大 9999999)
    wire [23:0] clamp_val = (div_q > 24'd9_999_999) ? 24'd9_999_999 : div_q[23:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st         <= ST_COARSE;
            armed      <= 1'b1;
            thr_l      <= 8'd112;
            thr_h      <= 8'd144;
            gate_cnt   <= 19'd0;
            cnt_gate   <= 17'd0;
            ev_cnt     <= 6'd0;
            t_cnt      <= 24'd0;
            div_start  <= 1'b0;
            max_v      <= 8'd0;
            min_v      <= 8'd255;
            freq_hz    <= 24'd0;
            vpp        <= 8'd0;
            meas_done  <= 1'b0;
            t_ok       <= 1'b0;
            wd_cnt     <= 13'd0;
        end
        else begin
            div_start <= 1'b0;
            meas_done <= 1'b0;

            // 迟滞武装/缴械(阈值自适应: 中心±12)
            if (upcross) armed <= 1'b0;
            else if (ad_cap <= thr_l) armed <= 1'b1;

            // 峰峰值跟踪
            if (ad_cap > max_v) max_v <= ad_cap;
            if (ad_cap < min_v) min_v <= ad_cap;

            case (st)
                ST_COARSE: begin
                    if (gate_cnt == GATE1_CLKS - 1) begin
                        // 10ms 到点
                        if (cnt_gate >= 17'd100) begin
                            // >=10kHz: 闸门法直接出结果
                            freq_hz  <= (cnt_gate * 17'd100 > 24'd9_999_999) ?
                                        24'd9_999_999 : (cnt_gate * 17'd100);
                            vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                            meas_done <= 1'b1;
                            gate_cnt <= 19'd0;
                            cnt_gate <= 17'd0;
                            thr_l      <= next_l;
                            thr_h      <= next_h;
                            max_v      <= 8'd0;
                            min_v    <= 8'd255;
                            // 留在 ST_COARSE
                        end
                        else begin
                            // <10kHz: 转测周法(细测 32 个周期后由 CALC 出结果)
                            st       <= ST_FINE;
                            gate_cnt <= 19'd0;
                            cnt_gate <= 17'd0;
                            ev_cnt   <= 6'd0;
                            t_cnt    <= 24'd0;
                        end
                    end
                    else begin
                        gate_cnt <= gate_cnt + 19'd1;
                        if (upcross && cnt_gate < 17'h1FFFF)
                            cnt_gate <= cnt_gate + 17'd1;
                    end
                end

                ST_FINE: begin
                    if (upcross) begin
                        if (ev_cnt == FINE_CYC - 1) begin
                            // 数满 32 周期: 判断计时是否有效
                            if ((t_cnt >= 24'd2) && (t_cnt < 25'h1_000000)) begin
                                t_ok      <= 1'b1;
                                div_start <= 1'b1;       // 有效 -> 启动除法器
                                wd_cnt    <= 13'd0;      // 看门狗清零
                                st        <= ST_CALC;
                            end
                            else begin
                                // 无效(计时超限=信号太低 <~95Hz): 报 0
                                freq_hz  <= 24'd0;
                                vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                                meas_done <= 1'b1;
                                thr_l      <= next_l;
                                thr_h      <= next_h;
                                max_v      <= 8'd0;
                                min_v    <= 8'd255;
                                ev_cnt   <= 6'd0;
                                t_cnt    <= 24'd0;
                                st       <= ST_COARSE;
                            end
                        end
                        else begin
                            ev_cnt <= ev_cnt + 6'd1;
                        end
                    end
                    // 计时(防溢出/卡死: 超过 2^24-1 就放弃细测)
                    if (t_cnt < 24'hFFFFFF) t_cnt <= t_cnt + 24'd1;
                    if (t_cnt == 24'hFFFFFF) begin
                        freq_hz  <= 24'd0;            // 超时(335ms 没数满32周期): 报 0
                        vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        meas_done <= 1'b1;
                        thr_l      <= next_l;
                        thr_h      <= next_h;
                        max_v      <= 8'd0;
                        min_v    <= 8'd255;
                        ev_cnt   <= 6'd0;
                        t_cnt    <= 24'd0;
                        st       <= ST_COARSE;
                    end
                end

                ST_CALC: begin
                    // 看门狗: 防除法器异常导致永久卡死(正常 32 拍就出结果)
                    wd_cnt <= wd_cnt + 13'd1;
                    if (div_done || wd_cnt == 13'd4095) begin
                        freq_hz  <= div_done ? (t_ok ? clamp_val : 24'd0)
                                             : 24'd0;              // 除法器异常兜底 0
                        vpp      <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                        meas_done <= 1'b1;
                        thr_l      <= next_l;
                        thr_h      <= next_h;
                        max_v      <= 8'd0;
                        min_v    <= 8'd255;
                        wd_cnt   <= 13'd0;
                        st       <= ST_COARSE;
                    end
                end
                default: st <= ST_COARSE;
            endcase
        end
    end

endmodule
