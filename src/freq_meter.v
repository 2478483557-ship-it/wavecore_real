//===========================================================================
// 模块名   : freq_meter
// 功能     : 频率计 + 峰峰值测量(M4b)
// 测量原理 : 开一个 10ms 的"闸门"(GATE), 在闸门内数 ad_cap 波形
//            向上穿过 128(中心电平)的次数 = 正弦周期数。
//            10ms 内数到 cnt 次 => 频率 = cnt x 100 Hz
//            (例: 1MHz 信号, 10ms 内有 10000 个周期 => 10000x100=1,000,000Hz)
//            误差: ±1 个计数, 对 100kHz(1000计数) 是 0.1%, 满足 <1%。
//            顺带跟踪窗内最大值/最小值 => Vpp = max - min
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module freq_meter #(
    parameter GATE_CLKS = 500_000      // 闸门长度: 500000 个时钟 = 10ms @50MHz
)(
    input  wire        clk,            // 系统时钟 50MHz
    input  wire        rst_n,          // 复位, 低有效
    input  wire [7:0]  ad_cap,         // 采集到的 ADC 数据(正弦)
    output reg  [15:0] freq_cnt,       // 闸门内的周期数(频率 = 该值 x100 Hz)
    output reg  [7:0]  vpp,            // 峰峰值 = max - min
    output reg         meas_done       // 每次测量结束, 输出一个脉冲
);

    reg [18:0] gate_cnt;   // 闸门计时(500000 需要 19 位)
    reg [15:0] cnt;        // 周期计数(带饱和保护, 防噪声溢出)
    reg [7:0]  max_v;      // 窗内最大值
    reg [7:0]  min_v;      // 窗内最小值
    reg [7:0]  ad_prev;    // 上一拍 ad_cap, 用来判断"向上穿越"

    // 向上穿越判断: 上一拍 <128 且这一拍 >=128 => 正弦走过一个周期的下半
    wire upcross = (ad_prev < 8'd128) && (ad_cap >= 8'd128);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            gate_cnt  <= 19'd0;
            cnt       <= 16'd0;
            freq_cnt  <= 16'd0;
            vpp       <= 8'd0;
            max_v     <= 8'd0;
            min_v     <= 8'd255;
            ad_prev   <= 8'd0;
            meas_done <= 1'b0;
        end
        else begin
            ad_prev <= ad_cap;             // 记住上一拍(每拍都更新)

            if (gate_cnt == GATE_CLKS - 1) begin
                // 闸门到点: 锁存结果, 开始下一轮
                freq_cnt  <= cnt;
                vpp       <= (max_v >= min_v) ? (max_v - min_v) : 8'd0;
                meas_done <= 1'b1;         // 通知外面"测完了"
                gate_cnt  <= 19'd0;
                cnt       <= 16'd0;
                max_v     <= 8'd0;
                min_v     <= 8'd255;
            end
            else begin
                meas_done <= 1'b0;
                gate_cnt  <= gate_cnt + 19'd1;
                if (upcross && cnt < 16'hFFFF)  // 饱和, 防止乱码噪声撑爆
                    cnt <= cnt + 16'd1;
                if (ad_cap > max_v) max_v <= ad_cap;
                if (ad_cap < min_v) min_v <= ad_cap;
            end
        end
    end

endmodule
