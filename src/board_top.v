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
    wire [31:0] fcw2;              // 第二路 NCO fcw(双音)
    wire [7:0]  rom_addr2;         // 第二路 ROM 地址
    wire [7:0]  sine2;             // 第二路正弦样点
    wire        dual_on;           // 双音模式
    wire        single_chg;        // 单音设定脉冲
    wire [7:0]  sine_out;          // 最终输出样点(单音或双音平均)
    wire [7:0]  ad_cap;            // 采集到的 ADC 数据
    wire [23:0] meas_freq;         // 频率计: 测量频率(Hz)
    wire [7:0]  meas_vpp;          // 频率计: 峰峰值
    wire        meas_done;         // 频率计: 测量完成脉冲
    wire [7:0]  rx_byte;           // uart_rx 收到的字节
    wire        rx_done;           // uart_rx 收完脉冲
    wire        preset_load;       // 串口切档命令脉冲
    wire [1:0]  preset_val;        // 串口目标档位
    wire        arb_load;          // 串口任意频率命令脉冲
    wire [31:0] arb_fcw;           // 串口任意频率 fcw
    wire        dual_load;         // 串口第二频率命令脉冲
    wire [31:0] dual_fcw;          // 串口第二频率 fcw

    // ---- 0. 按键消抖: key0 -> 单脉冲 ----
    key_debounce u_key (
        .clk       (sys_clk  ),
        .rst_n     (sys_rst_n),
        .key_in    (key0     ),
        .key_pulse (key_pulse)
    );

    // ---- 0.5 频率控制: 按键/串口切档/串口任意频率 -> fcw + LED ----
    freq_ctrl u_freq (
        .clk         (sys_clk     ),
        .rst_n       (sys_rst_n   ),
        .key_pulse   (key_pulse   ),
        .preset_load (preset_load ),
        .preset_val  (preset_val  ),
        .arb_load    (arb_load    ),
        .arb_fcw     (arb_fcw     ),
        .fcw         (fcw         ),
        .led         (led         ),
        .single_chg  (single_chg  )
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
        .preset_val  (preset_val  ),
        .arb_load    (arb_load    ),
        .arb_fcw     (arb_fcw     ),
        .dual_load   (dual_load   ),
        .dual_fcw    (dual_fcw    ),
        .wave_req    (wave_req_w  )
    );

    // ---- 0.8 双音模式控制(0x87 开双音, 任何单音设定自动回单音) ----
    dual_tone u_dual (
        .clk        (sys_clk     ),
        .rst_n      (sys_rst_n   ),
        .single_chg (single_chg  ),
        .dual_load  (dual_load   ),
        .dual_fcw   (dual_fcw    ),
        .dual       (dual_on     ),
        .fcw2       (fcw2        )
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
        .clk  (sys_clk  ),
        .addr (rom_addr ),
        .dout (sine     )
    );

    // ---- 2.5 第二路 NCO+ROM(双音用) ----
    dds_nco #(
        .PHASE_W (32),
        .ADDR_W  (8)
    ) u_nco2 (
        .clk      (sys_clk   ),
        .rst_n    (sys_rst_n ),
        .fcw      (fcw2      ),
        .rom_addr (rom_addr2 )
    );
    sine_rom u_rom2 (
        .clk  (sys_clk   ),
        .addr (rom_addr2 ),
        .dout (sine2     )
    );
    // 双音合成: 两路平均, 防溢出(各减直流再平均? 直接平均即可, 中心都~128)
    assign sine_out = dual_on ? {1'b0, sine[7:1]} + {1'b0, sine2[7:1]} : sine;

    // ---- 3. DAC 接口(时序对齐后送出) ----
    da_send u_da (
        .clk     (sys_clk  ),
        .sine_in (sine_out ),
        .da_clk  (da_clk   ),
        .da_data (da_data  )
    );

    // ---- 3.5 AD9280 驱动与采集(25MHz 采样 + 下降沿采集) ----
    ad_driver u_ad (
        .sys_clk   (sys_clk  ),
        .sys_rst_n (sys_rst_n),
        .ad_data   (ad_data  ),
        .ad_clk    (ad_clk   ),
        .ad_cap    (ad_cap   )
    );

    // ---- 3.6 频率计 v2: 自动双模式(闸门/测周), 直接出 Hz ----
    freq_meter u_meter (
        .clk       (sys_clk    ),
        .rst_n     (sys_rst_n  ),
        .ad_cap    (ad_cap     ),
        .freq_hz   (meas_freq  ),
        .vpp       (meas_vpp   ),
        .meas_done (meas_done  )
    );

    // ---- 3.7 测量结果经串口上报: "F=xxxxxxxHz V=xxx" ----
    measure_report u_report (
        .clk       (sys_clk    ),
        .rst_n     (sys_rst_n  ),
        .meas_done (meas_done  ),
        .freq_hz   (meas_freq  ),
        .vpp       (meas_vpp   ),
        .uart_txd  (m_txd      ),
        .meas_busy (m_busy     ),
        .ext_hold  (wav_hold   )
    );

    // ---- 3.8 FFT 频谱演示(B1 已点亮; 输出悬空供后续 B3 频谱显示) ----
    wire [23:0] fft_hz_w;        // FFT 主峰频率
    wire [23:0] fft_hz2_w;       // FFT 第二峰频率
    wire        fft_done_w;      // FFT 主峰完成
    wire        fft_done2_w;     // FFT 第二峰完成
    fft_demo u_fft_demo (
        .clk     (sys_clk    ),
        .rst_n   (sys_rst_n  ),
        .ad_cap  (ad_cap     ),
        .fft_hz  (fft_hz_w   ),
        .fft_hz2 (fft_hz2_w  ),
        .fft_done(fft_done_w ),
        .fft_done2(fft_done2_w)
    );

    // ---- 3.9 FFT 谱峰频率串口上报(B3): "S=xxxxxxxHz" ----
    wire        fft_txd;         // FFT 行 TX
    wire        fft_act;         // FFT 行占用标志
    wire        m_txd;           // 测量行 TX
    wire        m_busy;          // 测量行忙标志
    fft_report u_fft_rpt (
        .clk        (sys_clk    ),
        .rst_n      (sys_rst_n ),
        .meas_busy  (m_busy     ),
        .fft_done   (fft_done_w ),
        .fft_hz     (fft_hz_w   ),
        .fft_done2  (fft_done2_w),
        .fft_hz2    (fft_hz2_w  ),
        .uart_txd   (fft_txd    ),
        .fft_active (fft_act    ),
        .ext_hold   (wav_hold   )
    );
    // ---- 3.10 波形帧上传(F2-A): 0x83 请求 -> 传 1024 点(50kHz) ----
    wire        wave_req_w;    // 0x83 请求
    wire        wav_txd;       // 波形 TX
    wire        wav_act;       // 波形占用标志
    wire        wav_hold;      // 让测量/谱峰暂停
    wave_frame u_wave (
        .clk        (sys_clk   ),
        .rst_n      (sys_rst_n ),
        .ad_cap     (ad_cap    ),
        .req        (wave_req_w),
        .meas_busy  (m_busy    ),
        .fft_busy   (fft_act   ),
        .uart_txd   (wav_txd   ),
        .wav_active (wav_act   ),
        .wav_hold   (wav_hold  )
    );
    // TX 引脚 3 路互斥: 波形 > 谱峰 > 测量
    assign uart_txd = wav_act ? wav_txd : (fft_act ? fft_txd : m_txd);

    // ---- 4. ILA 片上逻辑分析仪(调试观察用) ----
    ila_0 u_ila (
        .clk    (sys_clk  ),
        .probe0 (da_data  ),
        .probe1 (rom_addr ),
        .probe2 (ad_cap   )
    );

endmodule
