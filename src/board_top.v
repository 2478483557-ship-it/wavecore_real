//===========================================================================
// 模块名   : board_top
// 功能     : 板上顶层(M4b) - 按键调频 + ADC 采集 + 自动测量 + 串口上报
// 版本历史 :
//   v1.0 M2   : fcw 写死 1MHz 出波
//   v1.1 M3   : KEY0 切 4 档频率, LED 显示档位
//   v1.2 M4a  : AD9280 采集(ad_clk 25MHz + 下降沿采样), ILA probe2=ad_cap
//   v1.3 M4b  : 频率计/峰峰值测量, 结果经串口 115200 上报电脑
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.3
//===========================================================================

module board_top (
    input  wire        sys_clk,    // 系统时钟 50MHz   (达芬奇Pro: R4)
    input  wire        sys_rst_n,  // 复位, 低有效      (达芬奇Pro: U7)
    input  wire        key0,       // 按键0: 切换频率档位 (达芬奇Pro: T4)
    output wire [3:0]  led,        // LED0~3: 档位指示 (达芬奇Pro: V9/Y8/Y7/W7)
    output wire        da_clk,     // DAC 锁存时钟      (AD9708: B20)
    output wire [7:0]  da_data,    // DAC 数据总线      (AD9708: C19~C13)
    output wire        ad_clk,     // ADC 采样时钟 25MHz (AD9280: D20)
    input  wire [7:0]  ad_data,    // ADC 数据总线      (AD9280: B22~D16)
    output wire        uart_txd,   // 串口发送 (CH340: D17, 115200)
    input  wire        uart_rxd    // 串口接收 (CH340: E14, 115200, M5 命令)
);

    wire [31:0] fcw;               // 频率控制字(由 freq_ctrl 决定)
    wire        key_pulse;         // 消抖后的按键脉冲
    wire [7:0]  rom_addr;          // NCO 输出的 ROM 地址
    wire [7:0]  sine;              // 查表得到的正弦样点
    wire [7:0]  ad_cap;            // 采集到的 ADC 数据
    wire [15:0] meas_cnt;          // 频率计: 周期计数
    wire [7:0]  meas_vpp;          // 频率计: 峰峰值
    wire        meas_done;         // 频率计: 测量完成脉冲
    wire [7:0]  rx_byte;           // uart_rx 收到的字节
    wire        rx_done;           // uart_rx 收完脉冲
    wire        preset_load;       // 串口切档命令脉冲
    wire [1:0]  preset_val;        // 串口目标档位

    // ---- 0. 按键消抖: key0 -> 单脉冲 ----
    key_debounce u_key (
        .clk       (sys_clk  ),
        .rst_n     (sys_rst_n),
        .key_in    (key0     ),
        .key_pulse (key_pulse)
    );

    // ---- 0.5 频率档位控制: 按键/串口命令 -> fcw + LED ----
    freq_ctrl u_freq (
        .clk         (sys_clk     ),
        .rst_n       (sys_rst_n   ),
        .key_pulse   (key_pulse   ),
        .preset_load (preset_load ),
        .preset_val  (preset_val  ),
        .fcw         (fcw         ),
        .led         (led         )
    );

    // ---- 0.7 串口接收 + 命令解析(M5a: 电脑切档) ----
    uart_rx u_rx (
        .clk     (sys_clk   ),
        .rst_n   (sys_rst_n ),
        .rxd     (uart_rxd  ),
        .rx_data (rx_byte   ),
        .rx_done (rx_done   )
    );

    cmd_decoder u_cmd (
        .clk         (sys_clk     ),
        .rst_n       (sys_rst_n   ),
        .rx_byte     (rx_byte     ),
        .rx_done     (rx_done     ),
        .preset_load (preset_load ),
        .preset_val  (preset_val  )
    );

    // ---- 1. 相位累加器(NCO) ----
    dds_nco #(
        .PHASE_W (32),
        .ADDR_W  (8)
    ) u_nco (
        .clk      (sys_clk  ),
        .rst_n    (sys_rst_n),
        .fcw      (fcw      ),
        .rom_addr (rom_addr )
    );

    // ---- 2. 正弦查找表 ----
    sine_rom u_rom (
        .addr (rom_addr ),
        .dout (sine     )
    );

    // ---- 3. DAC 接口(时序对齐后送出) ----
    da_send u_da (
        .clk     (sys_clk ),
        .sine_in (sine    ),
        .da_clk  (da_clk  ),
        .da_data (da_data )
    );

    // ---- 3.5 AD9280 驱动与采集(25MHz 采样 + 下降沿采集) ----
    ad_driver u_ad (
        .sys_clk   (sys_clk  ),
        .sys_rst_n (sys_rst_n),
        .ad_data   (ad_data  ),
        .ad_clk    (ad_clk   ),
        .ad_cap    (ad_cap   )
    );

    // ---- 3.6 频率计 + 峰峰值测量(10ms 闸门) ----
    freq_meter u_meter (
        .clk       (sys_clk    ),
        .rst_n     (sys_rst_n  ),
        .ad_cap    (ad_cap     ),
        .freq_cnt  (meas_cnt   ),
        .vpp       (meas_vpp   ),
        .meas_done (meas_done  )
    );

    // ---- 3.7 测量结果经串口上报: "F=xxxxxxxHz V=xxx" ----
    measure_report u_report (
        .clk       (sys_clk    ),
        .rst_n     (sys_rst_n  ),
        .meas_done (meas_done  ),
        .freq_cnt  (meas_cnt   ),
        .vpp       (meas_vpp   ),
        .uart_txd  (uart_txd   )
    );

    // ---- 4. ILA 片上逻辑分析仪(调试观察用) ----
    // 前置条件: IP Catalog 里已生成名为 ila_0 的 ILA IP
    // 注意 M4a: ila_0 需改为 3 个探针!
    // (Sample Depth=1024,
    //  probe0 宽8 接 da_data, probe1 宽8 接 rom_addr, probe2 宽8 接 ad_cap)
    ila_0 u_ila (
        .clk    (sys_clk  ),
        .probe0 (da_data  ),
        .probe1 (rom_addr ),
        .probe2 (ad_cap   )
    );

endmodule
