//===========================================================================
// 模块名   : dds_top
// 功能     : DDS 顶层(M1) - 例化 相位累加器 + 正弦查找表
// 说明     : 输入一个频率控制字 fcw, 输出 8bit 数字正弦样点 sine_out。
//            M1 阶段只做仿真验证(不接真实 DAC), 验证"数字波形是否正确"。
// 作者     : WaveCore 队长 | 日期: 2026-09-02 | 版本: v1.0
//===========================================================================

module dds_top (
    input  wire        sys_clk,    // 系统时钟 50MHz (达芬奇Pro: R4)
    input  wire        sys_rst_n,  // 复位, 低有效 (达芬奇Pro: U7)
    input  wire [31:0] fcw,        // 频率控制字(先由外部/testbench 给定)
    output wire [7:0]  sine_out    // 数字正弦样点(0~255, 中心 128)
);

    // 相位累加器输出的 ROM 地址
    wire [7:0] rom_addr;

    // ---- 例化 1: 相位累加器(NCO) ----
    dds_nco #(
        .PHASE_W (32),   // 与默认值一致, 写出来更清楚
        .ADDR_W  (8)
    ) u_nco (
        .clk      (sys_clk  ),
        .rst_n    (sys_rst_n),
        .fcw      (fcw      ),
        .rom_addr (rom_addr )
    );

    // ---- 例化 2: 正弦查找表 ----
    sine_rom u_rom (
        .addr (rom_addr ),
        .dout (sine_out )
    );

    // 注意: sine_rom 是组合逻辑(纯查表), 所以 sine_out 是"异步"变化的,
    // 波形上看起来是阶梯状, 这是正常的。
    // M2 接真实 DAC(AD9708)前, 会用 da_clk 把样点寄存一拍再输出,
    // 与官方例程 29_hs_ad_da 的做法一致, 到那时再处理。

endmodule
