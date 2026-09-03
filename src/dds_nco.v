//===========================================================================
// 模块名   : dds_nco
// 功能     : DDS 相位累加器（NCO 核心）
// 说明     : 每个时钟上升沿把 32 位相位累加器 phase_acc 加上频率控制字 fcw。
//            phase_acc 累加溢出(走满 2^32)一次 = 相位走完 360 度
//            = 输出波形完成一个正弦周期。
// 关键公式 : f_out = fcw x f_clk / 2^32
//            => fcw = f_out x 2^32 / f_clk
//            例: f_clk = 50MHz, 要 1MHz 输出:
//            fcw = 1000000 x 2^32 / 50000000 = 85899346 (0x051EB852)
//            频率分辨率(最小步进) = f_clk / 2^32 = 0.0116Hz, 足够精细
// 作者     : WaveCore 队长 | 日期: 2026-09-02 | 版本: v1.0
//===========================================================================

module dds_nco #(
    parameter PHASE_W = 32,   // 相位累加器位宽: 32 位频率分辨率很高
    parameter ADDR_W  = 8     // ROM 地址位宽: 2^8 = 256 点正弦表
)(
    input  wire               clk,      // 采样时钟 50MHz
    input  wire               rst_n,    // 复位, 低有效
    input  wire [PHASE_W-1:0] fcw,      // 频率控制字 Frequency Control Word
    output wire [ADDR_W-1:0]  rom_addr  // ROM 查表地址
);

    // 32 位相位累加器: 它是一个"寄存器", 属于时序逻辑
    reg [PHASE_W-1:0] phase_acc;

    // 时序逻辑标准写法: 时钟上升沿触发 + 异步复位
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            phase_acc <= {PHASE_W{1'b0}};      // 复位: 相位清零
        else
            phase_acc <= phase_acc + fcw;      // 每个时钟把相位往前推 fcw 步
    end

    // 相位截断: 32 位相位只取最高 ADDR_W 位当 ROM 地址。
    // 相当于把 2^32 个相位点"压缩"成 256 个采样点, 丢弃低 24 位。
    // 代价是微小的相位截断噪声(远小于 8bit DAC 的量化噪声, 可忽略)。
    assign rom_addr = phase_acc[PHASE_W-1 -: ADDR_W];

endmodule
