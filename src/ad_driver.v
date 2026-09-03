//===========================================================================
// 模块名   : ad_driver
// 功能     : 驱动 AD9280 并安全采集其数据(M4a)
// 1) 产生 25MHz 采样时钟 ad_clk 给 ADC:
//    AD9280 最高采样率约 28MSPS, 所以把 50MHz 二分频成 25MHz。
//    注意: ad_clk 由 50MHz 上升沿翻转产生, 所以它的上升沿和 sys_clk
//    的上升沿"对齐"。
// 2) 采集数据 ad_cap:
//    ADC 在 ad_clk 上升沿(即 sys_clk 上升沿)之后一小会儿才更新数据,
//    如果我们在 sys_clk 上升沿采样, 正好可能撞上数据切换, 采到乱码。
//    技巧: 在 sys_clk 的"下降沿"(比上升沿晚 10ns)采样 —— 此时数据
//    早已稳定, 而且仍在同一个 50MHz 时钟域里, 无需跨时钟域处理。
//    这就是官方例程用"相移时钟"抓 AD 数据的同款思路, 我们用下降沿
//    实现, 省掉一个 PLL。
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module ad_driver (
    input  wire        sys_clk,    // 系统时钟 50MHz
    input  wire        sys_rst_n,  // 复位, 低有效
    input  wire [7:0]  ad_data,    // AD9280 数据 (管脚 B22~D16)
    output reg         ad_clk,     // 25MHz 采样时钟, 送 ADC (管脚 D20)
    output reg  [7:0]  ad_cap      // 采集到的数据(安全采样, 供 ILA/测量用)
);

    // ---- 1. 25MHz 采样时钟: 50MHz 二分频 ----
    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n)
            ad_clk <= 1'b0;
        else
            ad_clk <= ~ad_clk;      // 每 20ns 翻转一次 => 25MHz 方波
    end

    // ---- 2. 采集: 在 sys_clk 下降沿采样(避开数据翻转瞬间) ----
    always @(negedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n)
            ad_cap <= 8'd0;
        else
            ad_cap <= ad_data;
    end

endmodule
