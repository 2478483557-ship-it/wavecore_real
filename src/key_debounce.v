//===========================================================================
// 模块名   : key_debounce
// 功能     : 按键消抖 + 单脉冲输出
// 为什么需要 : 机械按键按下时触点会"弹跳", 几毫秒内通断几十次。
//             FPGA 跑 50MHz, 不处理的话一次按键会被当成几十次按下。
// 处理思路   : 检测到按键按下(低电平)后开始计时, 只有连续稳定 20ms
//             仍然保持按下, 才认为"真的按了", 输出一个时钟宽度的脉冲;
//             松开(回到高电平)后自动复位, 等待下一次按下。
// 达芬奇Pro : key0 在 T4, 按下为低电平
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module key_debounce (
    input  wire clk,        // 系统时钟 50MHz
    input  wire rst_n,      // 复位, 低有效
    input  wire key_in,     // 按键输入, 低电平=按下
    output reg  key_pulse   // 输出: 确认按下时的一个时钟宽脉冲
);

    // 20ms 需要多少个时钟: 50MHz x 20ms = 1,000,000 个
    localparam CNT_20MS = 20'd1_000_000;

    // ---- 两级同步打拍: 把外部信号同步进时钟域, 防"亚稳态" ----
    // (亚稳态: 信号刚好在时钟沿附近变化时, 寄存器可能采到不确定值,
    //  打两拍让它有足够时间稳定下来。这是所有跨时钟输入的标准操作。)
    reg key_r1, key_r2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            key_r1 <= 1'b1;
            key_r2 <= 1'b1;
        end
        else begin
            key_r1 <= key_in;
            key_r2 <= key_r1;
        end
    end
    wire key_sync = key_r2;   // 同步后的按键值

    reg [19:0] cnt;           // 20ms 计时器
    reg        press_ok;      // 是否已经"确认按下"过(等待松手)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt       <= 20'd0;
            press_ok  <= 1'b0;
            key_pulse <= 1'b0;
        end
        else if (key_sync == 1'b0 && !press_ok) begin
            // 正在按下且还没确认: 计时
            if (cnt >= CNT_20MS) begin
                cnt       <= 20'd0;
                press_ok  <= 1'b1;      // 确认按下了
                key_pulse <= 1'b1;      // 只输出一拍脉冲
            end
            else begin
                cnt       <= cnt + 20'd1;
                key_pulse <= 1'b0;
            end
        end
        else if (key_sync == 1'b1) begin
            // 松开了: 全部复位, 等待下一次按下
            cnt       <= 20'd0;
            press_ok  <= 1'b0;
            key_pulse <= 1'b0;
        end
        else begin
            // 已确认按下且仍按着: 不动作
            key_pulse <= 1'b0;
        end
    end

endmodule
