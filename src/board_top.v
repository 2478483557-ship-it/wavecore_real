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
    input  wire        uart_rxd,   // 串口接收 (CH340: E14, 115200, M5 命令)
    output wire        uart_stm32_txd,  // F1 转发口: FPGA->STM32 (P1: N13, LVCMOS33)
    input  wire        uart_stm32_rxd   // F1 转发口: STM32->FPGA (P1: R14, LVCMOS33)
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
    wire [15:0] meas_duty;         // 频率计: 占空比(0.1%)
    wire [19:0] meas_wid;          // 频率计: 脉宽(us)
    wire        meas_done;         // 频率计: 测量完成脉冲
    wire        meas_done2;        // 频率计: 占空比/脉宽完成脉冲
    wire [23:0] sf_freq_w;         // 自研FFT: 峰值频率
    wire        sf_done_w;         // 自研FFT: 完成脉冲
    wire        sf_act_w;          // 自研FFT: 占用TX
    wire        sf_txd;            // 自研FFT: TX
    wire        sf_run_w;
    wire [1:0]  wave_type_w;       // 波形识别结果
    wire        sweep_en_w;        // 0x8B 扫频使能
    wire        sw_load_w;         // 扫频: 新频率脉冲
    wire [31:0] sw_fcw_w;          // 扫频: fcw          // 0x8A 运行一次
    wire [23:0] sf_f2_w;           // [调试] 第二峰
    wire [23:0] sf_f3_w;           // [调试] 第三峰
    wire [7:0]  rx_byte;           // uart_rx 收到的字节
    wire        rx_done;           // uart_rx 收完脉冲
    wire        preset_load;       // 串口切档命令脉冲
    wire [1:0]  preset_val;        // 串口目标档位
    wire        arb_load;          // 串口任意频率命令脉冲
    wire [31:0] arb_fcw;           // 串口任意频率 fcw
    wire        dual_load;         // 串口第二频率命令脉冲
    wire [31:0] dual_fcw;          // 串口第二频率 fcw
    wire [15:0] cal_kn_w;          // [0x8C] Vpp 电压标定: 每 LSB 多少 mV x1024

    // ---- 0. 按键消抖: key0 -> 单脉冲 ----
    key_debounce u_key (
        .clk       (sys_clk  ),
        .rst_n     (sys_rst_n),
        .key_in    (key0     ),
        .key_pulse (key_pulse)
    );

    // ---- 3.11c 扫频控制 (9/20): 与 0x85 共用 arb 通道(cmd 优先) ----
    sweep_ctrl u_sweep (
        .clk  (sys_clk  ),
        .rst_n(sys_rst_n),
        .en   (sweep_en_w),
        .load (sw_load_w),
        .fcw  (sw_fcw_w)
    );
    wire        arb_load_m = arb_load | sw_load_w;
    wire [31:0] arb_fcw_m  = arb_load ? arb_fcw : sw_fcw_w;

    // ---- 0.5 频率控制: 按键/串口切档/串口任意频率 -> fcw + LED ----
    freq_ctrl u_freq (
        .clk         (sys_clk     ),
        .rst_n       (sys_rst_n   ),
        .key_pulse   (key_pulse   ),
        .preset_load (preset_load ),
        .preset_val  (preset_val  ),
        .arb_load    (arb_load_m  ),
        .arb_fcw     (arb_fcw_m   ),
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

    // ---- F1 转发口下行: STM32 也可发命令(与 CH340 合并进同一个解码器) ----
    wire [7:0] rx2_byte;
    wire       rx2_done;
    uart_rx u_rx2 (
        .clk     (sys_clk      ),
        .rst_n   (sys_rst_n    ),
        .rxd     (uart_stm32_rxd),
        .rx_data (rx2_byte     ),
        .rx_done (rx2_done     )
    );
    wire [7:0] cmd_byte = rx2_done ? rx2_byte : rx_byte;
    wire       cmd_done = rx_done | rx2_done;

    // ---- 0.7b 命令解码输出线(先声明、后使用: 它们接在下面 cmd_decoder 的输出端口上) ----
    // ★ wave_sel_w / trig_mode_w 是 **2 位**。声明若写在文件后部, Verilog 会先按
    //   "隐式 1 位线网"建网, 端口位宽就对不上(靠工具宽容才没坏), 必须放在使用之前。
    wire       wave_req_w;     // 0x83 波形帧请求
    wire [1:0] wave_sel_w;     // 0x88 波形选择
    wire [1:0] trig_mode_w;

// ---- 0.7c [0x8D] 时基档位线(同样先声明、后使用) ----
wire        tb_set_w;    // 0x8D 命令生效脉冲
wire [1:0]  tb_sel_w;    // 目标档位 0/1/2/3 (T1/T2/T3/T4)
wire [31:0] tb_decim_w;  // 抽取比  -> 波形/自研FFT/IP FFT 三条通路
wire [31:0] tb_fs_w;     // 等效采样率(Hz) -> 所有频率换算(不许再写字面量 50000)    // 0x89 触发模式
wire        pre_set_w;   // [0x8F] 预触发档位生效脉冲
wire [1:0]  pre_sel_w;   // [0x8F] 预触发档 0=0%/1=25%/2=50%/3=75% -> wave_frame
wire        win_set_w;   // [0x90] 窗函数档位生效脉冲(未使用, 留作回执/闪灯)  [10-16]
wire [1:0]  win_cfg_w;   // [0x90] 窗函数 0=矩形 1=Hann 2=Blackman -> self_fft_1024
wire        ovl_set_w;   // [0x91] 帧重叠档位生效脉冲(留作回执)  [10-16]
wire        ovl_en_w;    // [0x91] 50% 帧重叠使能 -> self_fft_1024  [10-16]
wire        ifft_set_w;  // [0x92] IFFT 触发脉冲  [10-16]
wire [9:0]  ifft_lo_w;   // [0x92] 掩膜低 bin
wire [9:0]  ifft_hi_w;   // [0x92] 掩膜高 bin
wire        play_set_w;  // [0x93] 回放档位生效脉冲
wire        play_en_w;   // [0x93] 回放使能 -> self_fft_1024
wire [7:0]  da_play_w;   // [0x93] 回放样点 -> da_send
// [10-17] 0x94 状态回读: 三个 24 位值经 SF/S2/S3 三行发出
wire [23:0] dbg_rd1_w, dbg_rd2_w, dbg_rd3_w;

// ---- [10-17] 特征提取 + 神经网络推理（连续运行）----
// [10-19 修复] 这几个 wire 原**声明在 200 行之后**，而例化在本行之下 --
//   Verilog-2001 会把未声明的标识符**隐式声明成 1 位**。Vivado 综合恰好
//   取了后面的显式声明，所以实测正确；但换综合器可能真按 1 位处理：
//   nn_cls 是 2 位、被截成 1 位就只剩两类，nf_f0 是 16 位、被截位宽则特征全丢。
//   声明必须在首次使用之前 -- 这条 xvlog 会直接报 ERROR。
wire [15:0] nf_f0, nf_f1, nf_f2, nf_f3, nf_f4, nf_f5;
wire        nf_done, nn_done;
wire [1:0]  nn_cls;
reg  [31:0] nf_dcnt;       // 独立的抽取计数(与 self_fft 的采集互不干扰)
// ---- [10-21] 波形识别的自适应抽取比 ----
// 目的：让每周期样点数 spp = (50MHz/decim)/F 始终 >= 32。
// 依据：数值扫描表明 spp=8 时正弦与三角的判据区间完全重合（0.25~0.50），
//       spp>=32 才干净分离。实测原地固定 decim=1000（fs=50kHz），
//       正弦/三角在 5kHz 就崩，三档全对最高只到 3kHz。
//
// 取值原则：decim ≈ 390625/F，即 spp ≈ 128、窗口内恒定 16 个周期。
//   为省除法器，按倍频程分档取 2 的幂；每档顶端 spp ≈ 64，底端 ≈ 128。
//   低频段 decim 上限 1023（10 位计数器），此时 100Hz 窗内仍有 4 个周期，
//   与原设计（decim=1000）相当。
// 推导与实测见 report/wave_id_limit_2026-10-21.md。
reg [9:0] wid_decim;
always @(*) begin
    if      (meas_freq < 24'd763)    wid_decim = 10'd1023;
    else if (meas_freq < 24'd1526)   wid_decim = 10'd512;
    else if (meas_freq < 24'd3052)   wid_decim = 10'd256;
    else if (meas_freq < 24'd6104)   wid_decim = 10'd128;
    else if (meas_freq < 24'd12207)  wid_decim = 10'd64;
    else if (meas_freq < 24'd24414)  wid_decim = 10'd32;
    // [10-21 实测] 抽取比不能低于 32。
    //   上板对比：decim=32（fs=1.56MHz）-> 24kHz 稳定 5/5；
    //             decim=16（fs=3.13MHz）-> 26kHz 全错 0/5，而 spp 反而更高（120）。
    //   说明限制来自**采样率**而非样点数：DDS 输出是 50MHz 台阶波形，
    //   采得越快，台阶/毛刺占比越大，形状统计被破坏。
    //   故 fs 上限锁在 1.5625MHz -> spp>=32 的最高频率约 48.8kHz。
    //   （若用外部信号源而非板上回环，这个上限可能更高，待验。）
    else                             wid_decim = 10'd32;
end

// [10-21] 神经网络的特征提取也改走自适应抽取。
//   原来固定 tb_decim_w（T1=1000 -> 50kHz），每周期样点随频率掉，
//   实测网络在 20kHz 以上全错。
//   注意 not 用 tb_decim_w：那是时基，与波形识别无关。
wire        nf_tick = (nf_dcnt >= ({22'd0, wid_decim} - 32'd1));

always @(posedge sys_clk or negedge sys_rst_n) begin
    if (!sys_rst_n) nf_dcnt <= 32'd0;
    else if (nf_tick) nf_dcnt <= 32'd0;
    else              nf_dcnt <= nf_dcnt + 32'd1;
end

wave_feat u_nnfeat (
    .clk     (sys_clk   ),
    .rst_n   (sys_rst_n ),
    .start   (1'b1          ),   // 永久拉高 -> 采满一帧后自动重新开始
    .din     (ad_cap ^ 8'h80),   // 偏移二进制 -> 补码
    .din_valid(nf_tick  ),
    .f0(nf_f0), .f1(nf_f1), .f2(nf_f2), .f3(nf_f3), .f4(nf_f4), .f5(nf_f5),
    .done    (nf_done   ),
    .dbg_st  (          ),
    .dbg_op  (          )
);

wave_nn #(.SH1(14), .SH2(11)) u_nn (
    .clk   (sys_clk ),
    .rst_n (sys_rst_n),
    .start (nf_done ),
    .f0(nf_f0), .f1(nf_f1), .f2(nf_f2), .f3(nf_f3), .f4(nf_f4), .f5(nf_f5),
    .cls   (nn_cls  ),
    .done  (nn_done ),
    .dbg_st(        )
);

// [10-19 修复] 这 5 个信号原来声明在下面 20 多行之后，但这里就要用。
//   Verilog-2001 会把未声明标识符隐式声明成 1 位 wire；nn_cls_r 本来是 2 位，
//   一旦被按 1 位处理，神经网络的 4 个类别就退化成 2 个 -- 而这种错误
//   在 Vivado 里只报 warning，不会拦住综合。声明必须在使用之前。
reg  [1:0]  nn_cls_r;      // 锁存最近一次的识别结果
wire        dbg_read_w;    // 0x94 触发脉冲
wire        dbg_nn_w;      // 0x95 触发脉冲
reg         dbg_is_nn;
reg         dbg_req_d;

always @(posedge sys_clk or negedge sys_rst_n) begin
    if (!sys_rst_n)              nn_cls_r <= 2'd3;
    else if (nn_done)            nn_cls_r <= nn_cls;
end

// 0x95 的编码: 沿用 0x94 的三行, 换个前缀 700000 便于区分
//   SF = 700000 + 类别(1..4)    类别: 1=正弦 2=方波 3=三角 4=其他
//   S2 = f0 占空比 (Q15)        S3 = f2 峭度 (Q15)
wire [23:0] nn_rd1 = 24'd700000 + {22'd0, nn_cls_r} + 24'd1;
wire [23:0] nn_rd2 = {8'd0, nf_f0};
wire [23:0] nn_rd3 = {8'd0, nf_f2};

// 数据源选择: 0x95 的脉冲来得早, 用打一拍后的 dbg_req 触发, 此时 dbg_is_nn 已更新
// [10-23] 回读源改成三选一: 0=0x94 反向变换状态 1=0x95 神经网络 2=0x9D 波形识别
//   0x9D: SF = 800000 + 类型(0..3)   S2 = span   S3 = hi_cnt
wire [23:0] wd_rd1 = 24'd800000 + {22'd0, wave_type_w};
wire [23:0] wd_rd2 = {16'd0, wid_span_w};
wire [23:0] wd_rd3 = {12'd0, wid_hi_w};
// [10-24] 0x9E: fft_report 内部状态
//   SF = 900000 + dbg_state(8位拆成十进制: 状态位图按二进制解释后加前缀)
//   S2 = idle_cnt >> 8 (低 8 位没意义, 只看量级)
//   S3 = dbg_state 的十进制值(方便直接读)
wire [23:0] fr_rd1 = 24'd900000 + {16'd0, fr_state_w};
wire [23:0] fr_rd2 = {5'd0, fr_idle_w[18:8]};
wire [23:0] fr_rd3 = {16'd0, fr_state_w};
reg  [1:0]  dbg_src;
always @(posedge sys_clk or negedge sys_rst_n) begin
    if (!sys_rst_n)       dbg_src <= 2'd0;
    else if (dbg_nn_w)    dbg_src <= 2'd1;
    else if (dbg_wd_w)    dbg_src <= 2'd2;
    else if (dbg_fr_w)    dbg_src <= 2'd3;
    else if (dbg_read_w)  dbg_src <= 2'd0;
end
always @(posedge sys_clk or negedge sys_rst_n) begin
    if (!sys_rst_n) dbg_req_d <= 1'b0;
    else            dbg_req_d <= dbg_read_w | dbg_nn_w | dbg_wd_w | dbg_fr_w;
end

wire [23:0] dbg_v1 = (dbg_src == 2'd1) ? nn_rd1 :
                     (dbg_src == 2'd2) ? wd_rd1 :
                     (dbg_src == 2'd3) ? fr_rd1 : dbg_rd1_w;
wire [23:0] dbg_v2 = (dbg_src == 2'd1) ? nn_rd2 :
                     (dbg_src == 2'd2) ? wd_rd2 :
                     (dbg_src == 2'd3) ? fr_rd2 : dbg_rd2_w;
wire [23:0] dbg_v3 = (dbg_src == 2'd1) ? nn_rd3 :
                     (dbg_src == 2'd2) ? wd_rd3 :
                     (dbg_src == 2'd3) ? fr_rd3 : dbg_rd3_w;
// [10-17] 识别来源切换: 0=TY 规则法(默认, 与升级前一致) 1=神经网络
wire        ty_src_sel_w;
wire        win_auto_w;      // [0x97] 自适应选窗
wire        avg_en_w;        // [0x98] 谱平均
wire [1:0]  ty_show;          // 最终送给 TY= 行的类别
wire [1:0]  win_now_w;        // [10-18] 实际生效的窗 -> 上报 WIN= 行
// 规则法原生编码: 0=方波 1=正弦 2=三角 3=其他
// 神经网络编码:   0=正弦 1=方波 2=三角 3=其他
//   -> 选 NN 时要把 0/1 互换, 才能让 TY= 行保持同一套语义
wire [1:0]  nn_as_ty = {nn_cls_r[1], ~(nn_cls_r[0] ^ nn_cls_r[1])};
assign ty_show = ty_src_sel_w ? nn_as_ty : wave_type_w;
// 0x94/0x95 共用同一条上报通路, 用这个标志选数据源

    // ---- 0.7c [0x8E] 幅度谱帧相关线(同样必须先声明后使用; 下方 3.7/3.9 会用到) ----
    wire        spec_req_w;    // 0x8E 请求脉冲(cmd_decoder 输出)
// [10-23] 锁相放大 / 噪声注入
wire [3:0]  lk_noise_w;      // [0x99] 噪声档位(4 位! 写成 1 位会把档位截成 0/1)
wire [2:0]  lk_att_w;        // [0x99] 信号衰减
wire        lk_en_w;         // [0x9A]
wire        lk_req_w;        // [0x9B]
wire [15:0] lk_per_w;        // [0x9C]
wire [7:0]  sine_mix;        // DDS 波形叠加噪声后的结果
wire signed [47:0] lk_i_w, lk_q_w;
wire [31:0] lk_n_w;
wire        lk_done_w, lk_act_w, lk_txd_w;
// [10-23] 0x9D 波形识别内部量回读
wire        dbg_wd_w;
// [10-24] 0x9E: fft_report 内部状态
wire        dbg_fr_w;
wire [7:0]  fr_state_w;
wire [18:0] fr_idle_w;
wire [7:0]  wid_span_w;
wire [11:0] wid_hi_w;
    wire        spec_run_w;    // spec_frame -> self_fft 运行脉冲
    wire [7:0]  spec_wdata_w;  // 谱缓存写数据
    wire [8:0]  spec_waddr_w;  // 谱缓存写地址
    wire        spec_we_w;     // 谱缓存写使能
    wire [8:0]  spec_raddr_w;  // 谱缓存读地址
    wire [7:0]  spec_rdata_w;  // 谱缓存读数据
    wire        spec_txd;      // 谱帧 TX
    wire        spec_act_w;    // 谱帧占用 TX
    wire        spec_hold_w;   // 谱帧请求期间暂停其它行
    wire        sf_busy_w;     // 自研FFT 运行中

    cmd_decoder u_cmd (
        .clk         (sys_clk     ),
        .rst_n       (sys_rst_n   ),
        .rx_byte     (cmd_byte    ),
        .rx_done     (cmd_done    ),
        .preset_load (preset_load ),
        .preset_val  (preset_val  ),
        .arb_load    (arb_load    ),
        .arb_fcw     (arb_fcw     ),
        .dual_load   (dual_load   ),
        .dual_fcw    (dual_fcw    ),
        .wave_req    (wave_req_w  ),
        .wave_sel    (wave_sel_w  ),
        .trig_mode   (trig_mode_w ),
        .tb_set      (tb_set_w    ),
        .tb_sel      (tb_sel_w    ),
        .pre_set     (pre_set_w   ),   // [0x8F] 预触发
        .pre_sel     (pre_sel_w   ),
        .win_set     (win_set_w   ),   // [0x90] 窗函数
        .win_sel     (win_cfg_w   ),
        .ovl_set     (ovl_set_w   ),   // [0x91] 50% 帧重叠
        .ovl_sel     (ovl_en_w    ),
        .ifft_set    (ifft_set_w  ),   // [0x92] IFFT 频域滤波
        .ifft_lo     (ifft_lo_w   ),
        .ifft_hi     (ifft_hi_w   ),
        .play_set    (play_set_w  ),   // [0x93] IFFT 结果回放
        .play_sel    (play_en_w   ),
        .dbg_read    (dbg_read_w  ),   // [0x94] 状态回读
        .dbg_nn      (dbg_nn_w    ),   // [0x95] 神经网络结果
        .ty_src_sel  (ty_src_sel_w),   // [0x96] 识别来源
        .win_auto    (win_auto_w  ),   // [0x97] 自适应选窗 (之前漏接, 功能一直不生效)
        .avg_en      (avg_en_w    ),   // [0x98] 谱平均     (之前漏接, 功能一直不生效)
        .sf_run      (sf_run_w    ),
        .sweep_en    (sweep_en_w  ),
        .cal_kn      (cal_kn_w    ),
        .spec_req    (spec_req_w  ),
        .lk_noise    (lk_noise_w  ),   // [0x99] 噪声档位
        .lk_att      (lk_att_w    ),   // [0x99] 信号衰减
        .lk_en       (lk_en_w     ),   // [0x9A] 锁相放大使能
        .lk_req      (lk_req_w    ),   // [0x9B] 请求 I/Q 帧
        .lk_per      (lk_per_w    ),   // [0x9C] 积分周期数
        .dbg_wd      (dbg_wd_w     ),  // [0x9D] 波形识别内部量回读
        .dbg_fr      (dbg_fr_w     )   // [0x9E] fft_report 内部状态
        // .cal_load 悬空: 标定值本身是带记忆的寄存器, 脉冲只是预留回执/指示用
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
    // ---- 2.7 波形选择(F5, 0x88): 0=正弦 1=方波 2=三角 ----
    wire [7:0] tri_a = {1'b0, (rom_addr[7]  ? (8'd255 - rom_addr[7:0])  : rom_addr[7:0])}  << 1;
    wire [7:0] tri_b = {1'b0, (rom_addr2[7] ? (8'd255 - rom_addr2[7:0]) : rom_addr2[7:0])} << 1;
    // [09-30 修复] 方波电平原为写死的 26 / 230 (Vpp 204 LSB), 而正弦(sine_256.hex)
    //   是 1 / 255、三角是 0 / 254 (Vpp 254 LSB)。于是同一块板子上三种波形测出的
    //   Vpp 不一样(实测正弦 V=1085mV、方波 V=0882mV, 比值 0.813 与数字比 204/254=0.803 吻合),
    //   演示/答辩时会被当成"幅度不准"。
    //   现统一为与正弦完全相同的 1 / 255 (Vpp 254 LSB), 中点都还是 128。
    //   影响面已核对:
    //     - wave_id 波形识别: 全程用 mn/mx/span 归一化, **与绝对幅度无关**, 不受影响;
    //     - 占空比/脉宽: 看的是跳变位置, 与幅度无关;
    //     - 自研FFT 的 SF/S2/S3(bin20/61/102): 数值模型验证过, **一个数都没变**;
    //     - 双音合成 {1'b0,wave[7:1]} 相加: 255>>1=127, 127+127=254, 不会溢出。
    wire [7:0] wave_a = (wave_sel_w == 2'd1) ? (rom_addr[7]  ? 8'd1 : 8'd255) :   // 方波
                        (wave_sel_w == 2'd2) ? tri_a : sine;
    wire [7:0] wave_b = (wave_sel_w == 2'd1) ? (rom_addr2[7] ? 8'd1 : 8'd255) :
                        (wave_sel_w == 2'd2) ? tri_b : sine2;
    // 双音合成(对整形后的波形)
    assign sine_out = dual_on ? {1'b0, wave_a[7:1]} + {1'b0, wave_b[7:1]} : wave_a;

    // ---- 3. DAC 接口(时序对齐后送出) ----
    // [10-23] 锁相演示用：给 DDS 波形叠加伪随机噪声、并可衰减信号本身。
    //   noise=0 / att=0 时输出与原来逐位相同（增益通路是纯组合的加减与移位）。
    sig_noise u_sn (
        .clk  (sys_clk    ),
        .rst_n(sys_rst_n  ),
        .din  (sine_out   ),
        .level(lk_noise_w ),
        .shift(lk_att_w   ),
        .dout (sine_mix   )
    );

    da_send u_da (
        .clk     (sys_clk  ),
                // [10-16] 回放使能时用 IFFT 结果驱动 DAC, 否则仍由 DDS 驱动(DDS 功能不受影响)
        // [10-23] 注噪/衰减都关时直接旁路，保证与加功能之前逐位相同
        .sine_in (play_en_w ? da_play_w :
                  ((lk_noise_w == 4'd0 && lk_att_w == 3'd0) ? sine_out : sine_mix)),
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

    // ---- 3.55 数字锁相放大 [10-23] ----
    //   与 DDS 共用同一个频率字，构成"同源参考"的相干解调。
    //   关闭时累加器清零，不占用 TX、不影响任何既有功能。
    lockin_core u_lk (
        .clk   (sys_clk   ),
        .rst_n (sys_rst_n ),
        .ad_cap(ad_cap    ),
        .fcw   (fcw       ),
        .en    (lk_en_w   ),
        .m_per (lk_per_w  ),
        .i_out (lk_i_w    ),
        .q_out (lk_q_w    ),
        .n_out (lk_n_w    ),
        .done  (lk_done_w )
    );

    lockin_frame u_lkf (
        .clk      (sys_clk ),
        .rst_n    (sys_rst_n),
        .req      (lk_req_w),
        .lk_busy  (spec_act_w | wav_act | fft_act | sf_act_w),
        .i_val    (lk_i_w  ),
        .q_val    (lk_q_w  ),
        .n_val    (lk_n_w  ),
        .uart_txd (lk_txd_w),
        .lk_active(lk_act_w)
    );

    // ---- 3.55 调试观察信号(专供 ILA) ----
    // ★ 这 4 根 wire 要接到下面 3.6 / 3.7 段模块的 .dbg_* 端口上, 所以**必须在这里声明**。
    //   千万不要挪到文件后部的 ILA 段去 -- 位置在使用之后 = Verilog 先建"隐式 1 位线网",
    //   后面再写显式声明就是重复声明, 而且 3 位端口接到 1 位线网上高位会悬空
    //   (xvlog 会报 `VRFC 10-2938 'x' is already implicitly declared`)。
    wire [2:0]  meter_dbg_st;     // freq_meter 内部 FSM 状态
    wire [7:0]  meas_dbg_fsm;     // measure_report 内部 FSM 状态
    wire [31:0] meter_h_tick;     // freq_meter 的闸门/测周计数
    wire [31:0] meter_p_tick;     // measure_report 的脉宽计数

    // ---- 3.6 频率计 v2: 自动双模式(闸门/测周), 直接出 Hz ----
    freq_meter u_meter (
        .clk        (sys_clk    ),
        .rst_n      (sys_rst_n  ),
        .ad_cap     (ad_cap     ),
        .freq_hz    (meas_freq  ),
        .vpp        (meas_vpp   ),
        .duty_x10   (meas_duty  ),
        .width_us   (meas_wid   ),
        .meas_done  (meas_done  ),
        .meas_done2 (meas_done2 ),
        .dbg_st     (meter_dbg_st),
        .dbg_h_tick (meter_h_tick),
        .dbg_p_tick (meter_p_tick)
    );

    // ---- 3.65 上报占用 / 波形暂停标志(先声明、后使用) ----
    wire        m_txd;           // 测量行 TX
    wire        m_busy;          // 测量行忙标志
    wire        wav_hold;        // 波形上传期间让测量/谱峰暂停

    // ---- 3.7 测量结果经串口上报: "F=xxxxxxxHz V=xxxx" (V 为 mV) ----
    measure_report u_report (
        .clk        (sys_clk    ),
        .rst_n      (sys_rst_n  ),
        .meas_done  (meas_done  ),
        .freq_hz    (meas_freq  ),
        .vpp        (meas_vpp   ),
        .meas_done2 (meas_done2 ),
        .duty_x10   (meas_duty  ),
        .wave_type  (ty_show     ),   // [10-18 修复] 这里原来接 wave_type_w, 但被下面 wave_id 改接到 ty_show 后, 该线无人驱动 -> 综合成 0 -> TY 恒为"方波"
        .width_us   (meas_wid   ),
        .uart_txd   (m_txd      ),
        .meas_busy  (m_busy     ),
        .ext_hold   (wav_hold | sf_act_w | spec_hold_w),
        .dbg_fsm    (meas_dbg_fsm),
        .dbg_h_tick (meter_h_tick),
        .dbg_p_tick (meter_p_tick),
        .cal_kn     (cal_kn_w   )
    );

    // ---- 3.8 FFT 频谱演示(B1 已点亮; 输出悬空供后续 B3 频谱显示) ----
    wire [23:0] fft_hz_w;        // FFT 主峰频率
    wire [23:0] fft_hz2_w;       // FFT 第二峰频率
    wire        fft_done_w;      // FFT 主峰完成
    wire        fft_done2_w;     // FFT 第二峰完成
    // ---- 3.35 [0x8D] 时基档位: 50k(默认)/12.5k/100k ----
    timebase u_timebase (
        .clk     (sys_clk  ),
        .rst_n   (sys_rst_n),
        .set     (tb_set_w ),
        .sel_in  (tb_sel_w ),
        .decim   (tb_decim_w),
        .fs_hz   (tb_fs_w  ),
        .sel_out (         )
    );

    // [10-23] 给 IP 核 FFT 一个**安全的抽取比**。
    //   根因：xfft 核的 C_HAS_ARESETN=0，**没有复位端口**。
    //     T3/T4 的 decim=8/4 会让它进入无法恢复的状态，此后 S=/A= 永久停发，
    //     切回 T1 也不复活（实测；加过计数器复位、采集闸门、ST_WAIT 看门狗，均无效）。
    //   处置：与 wave_frame 同样思路——高频档不让它接触 decim<100。
    //     T1/T2 行为与升级前逐位相同；T3/T4 时 IP 核按 50kHz 继续工作。
    //   代价：T3/T4 下 S=/A= 只覆盖 0~25kHz（高频谱线由自研 FFT 与谱帧提供）。
    wire [31:0] fft_decim_w = (tb_decim_w >= 32'd100) ? tb_decim_w : 32'd1000;
    wire [31:0] fft_fs_w    = (tb_decim_w >= 32'd100) ? tb_fs_w

                                                       : 32'd50000;

    fft_demo u_fft_demo (
        .clk     (sys_clk    ),
        .rst_n   (sys_rst_n  ),
        .ad_cap  (ad_cap     ),
        .decim_cfg(fft_decim_w),   // [10-23] 高频档回落到 1000，见上
        .fs_cfg  (fft_fs_w   ),
        .fft_hz  (fft_hz_w   ),
        .fft_hz2 (fft_hz2_w  ),
        .fft_done(fft_done_w ),
        .fft_done2(fft_done2_w)
    );

    // ---- 3.9 FFT 谱峰频率串口上报(B3): "S=xxxxxxxHz" ----
    wire        fft_txd;         // FFT 行 TX
    wire        fft_act;         // FFT 行占用标志
    // m_txd / m_busy 的声明已上移到 3.65 段(必须先声明后使用)
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
        .dbg_state  (fr_state_w ),   // [0x9E]
        .dbg_idle   (fr_idle_w  ),
        .ext_hold   (wav_hold | sf_act_w | spec_hold_w)
    );
    // ---- 3.10 波形帧上传(F2-A): 0x83 请求 -> 传 1024 点(50kHz) ----
    // wave_req_w / wave_sel_w / trig_mode_w 的声明已上移到 0.7b 段;
    // wav_hold 的声明已上移到 3.65 段(都必须先声明后使用)
    wire        wav_txd;       // 波形 TX
    wire        wav_act;       // 波形占用标志
    wave_frame u_wave (
        .clk        (sys_clk   ),
        .rst_n      (sys_rst_n ),
        .ad_cap     (ad_cap    ),
        // [10-23] 波形帧固定用 50kHz(decim=1000), 不再跟随 0x8D 时基。
        //   原因: 高频档(decim 4/8)下波形缓存根本凑不满, 会残留忙态,
        //   而且切回 T1 后也恢复不了 —— 波形通路被彻底拖死。
        //   频谱(0x8A/0x8E)仍然用 tb_decim_w, 高频观察走频谱。
        .decim_cfg  (32'd1000),
        .req        (wave_req_w),
        .trig_mode  (trig_mode_w),
        .pre_cfg    (pre_sel_w ),   // [0x8F] 预触发档(0=0% 1=25% 2=50% 3=75%)
        .meas_busy  (m_busy    ),
        .fft_busy   (fft_act | spec_act_w),   // 谱帧发送期间也让波形请求等着
        .uart_txd   (wav_txd   ),
        .wav_active (wav_act   ),
        .wav_hold   (wav_hold  )
    );
    // TX 引脚 3 路互斥: 波形 > 谱峰 > 测量
    // ---- 3.11b 波形自动识别(9/20): 占比法, 输出 TY= 行 ----

    wave_id u_wid (
        .clk      (sys_clk    ),
        .rst_n    (sys_rst_n  ),
        .ad_cap   (ad_cap     ),
        .decim_cfg(wid_decim  ),              // [10-21] 自适应抽取比
        .wave_type(wave_type_w),              // 规则法原始结果(0=方波 1=正弦 2=三角 3=其他)
        .dbg_span (wid_span_w ),              // [0x9D] 调试回读
        .dbg_hi   (wid_hi_w   )
    );

    // ---- 3.12 自研FFT(F4 复活版, 2026-09-17): 1024点 DIF, 0x8A 按需, SF= 行 ----
    self_fft_1024 u_scfft (
        .clk      (sys_clk   ),
        .rst_n    (sys_rst_n ),
        .ad_cap   (ad_cap    ),
        .decim_cfg(tb_decim_w),
        .fs_cfg   (tb_fs_w   ),
        .win_cfg  (win_cfg_w ),
        .win_auto (win_auto_w),   // [0x97] 自适应选窗
        .avg_en   (avg_en_w  ),   // [0x98] 谱平均
        .ovl_en   (ovl_en_w  ),   // [0x91] 50% 帧重叠
        .play_en  (play_en_w ),   // [0x93] IFFT 结果回放
        .da_play  (da_play_w ),
        .inv_run  (ifft_set_w),   // [0x92] IFFT 频域滤波
        .mask_lo  (ifft_lo_w ),
        .mask_hi  (ifft_hi_w ),   // [0x90] 窗函数运行时可切换
        .run      (sf_run_w | spec_run_w),   // 0x8A 或 0x8E 都触发一次运行
        .res_freq (sf_freq_w ),
        .res_f2   (sf_f2_w   ),
        .res_f3   (sf_f3_w   ),
        .res_done (sf_done_w ),
        .spec_we  (spec_we_w ),
        .spec_waddr(spec_waddr_w),
        .spec_wdata(spec_wdata_w),
        .busy     (sf_busy_w ),
        .win_now  (win_now_w ),   // [10-18] 实际生效的窗
        .dbg_rd1 (dbg_rd1_w),   // [10-17] 0x94 状态回读
        .dbg_rd2 (dbg_rd2_w),
        .dbg_rd3 (dbg_rd3_w)
    );
    self_fft_report u_sfrpt (
        .clk      (sys_clk   ),
        .rst_n    (sys_rst_n ),
        .res_freq (sf_freq_w ),
        .res_f2   (sf_f2_w   ),
        .res_f3   (sf_f3_w   ),
        .res_done (sf_done_w & ~spec_hold_w), // 0x8E 触发的运行不报 SF 行(防抢 TX)
        .win_now  (win_now_w ),               // [10-18] 上报 WIN= 行
        .m_busy   (m_busy    ),
        .fft_act  (fft_act   ),
        .wav_act  (wav_act | spec_act_w),     // 谱帧发送期间也让路
        .uart_txd (sf_txd    ),
        .sf_active(sf_act_w  ),
        // [10-17] 0x94 状态回读
        .dbg_req  (dbg_req_d ),
        .dbg_v1   (dbg_v1    ),
        .dbg_v2   (dbg_v2    ),
        .dbg_v3   (dbg_v3    )
    );

    // ---- 3.13 [0x8E] 幅度谱帧: 缓存 + 发送 (2026-09-30 新增) ----
    // 链路: self_fft 扫描时写 spec_buf -> 0x8E 触发一次运行 -> spec_frame
    //       等运行完成后把 512 点幅度顺序发出(518 字节帧)
    spec_buf u_specbuf (
        .clk   (sys_clk      ),
        .we    (spec_we_w    ),
        .waddr (spec_waddr_w ),
        .wdata (spec_wdata_w ),
        .raddr (spec_raddr_w ),
        .rdata (spec_rdata_w )
    );
    spec_frame u_specframe (
        .clk          (sys_clk      ),
        .rst_n        (sys_rst_n    ),
        .req          (spec_req_w   ),
        .sf_busy      (sf_busy_w    ),
        .fft_done     (sf_done_w    ),
        .meas_busy    (m_busy       ),
        .fft_busy     (fft_act      ),
        .wav_busy     (wav_act      ),
        .sf_line_busy (sf_act_w     ),
        .fft_run      (spec_run_w   ),
        .rdata        (spec_rdata_w ),
        .raddr        (spec_raddr_w ),
        .uart_txd     (spec_txd     ),
        .spec_active  (spec_act_w   ),
        .spec_hold    (spec_hold_w  )
    );

    // TX 引脚 5 路互斥: 谱帧 > 波形 > 谱峰 > 自研FFT > 测量
    assign uart_txd = lk_act_w ? lk_txd_w : (spec_act_w ? spec_txd : (wav_act ? wav_txd : (fft_act ? fft_txd :
                      (sf_act_w ? sf_txd : m_txd))));

    // ---- 3.11 F1 转发口: 把整条串口数据流镜像给 STM32 ----
    uart_mirror u_mirror (
        .clk     (sys_clk        ),
        .rst_n   (sys_rst_n      ),
        .src_txd (uart_txd       ),
        .dst_txd (uart_stm32_txd )
    );

    // ---- 4. ILA 片上逻辑分析仪(调试观察用) ----
    // [09-16 临时禁用: 布局余量不足(当时 LUT 超容)]
    // [09-30 重新打开: 资源攻坚后 LUT 只占 24.60%、BRAM 20%、DSP 30%, 余量充足。
    //                  见 report/lut_slim_report.md / report/resource_compare.md]
    //
    // ★ 一键开关: ILA_EN=1 才有 ILA；交付版保持 0。
    //   注意 1'b0 时整块 ILA **连同它的调试桥(dbg_hub)一起被 generate 掉**, 资源占用回到
    //   与"无 ILA 版"完全一致 -- 也就是说这个开关是零代价的。
    //   最终提交版若要把资源压到极致, 改成 1'b0 即可(功能一行都不受影响)。
    //
    // 探针口径(与 ILA IP 里配的 3 个 probe 均为 8 位对齐):
    //   probe0 = {5'b0, meter_dbg_st}  频率计的 FSM 状态(0~7)
    //   probe1 = meas_dbg_fsm          上报模块的 FSM 状态
    //   probe2 = {7'b0, wav_hold}      波形上传期间的"暂停测量"标志
    //   (wav_hold 已在上面 3.10 段声明, 这里不再重复声明)
    // [10-18] 关闭: 交付/演示版不需要 ILA。实测它占 729 LUT + 1253 FF + 1 块 RAMB36
    //   占总资源 LUT 3.5% / FF 3.0%。关掉后 LUT 41.32% -> 37.8%, FF 20.37% -> 17.3%。
    //   要重新调试时改回 1'b1 再综合即可（8~15 分钟）。
    localparam ILA_EN = 1'b0;
    // ★ 被观察的 4 根 wire 已在上方 **3.55 段**声明(必须在使用前), 这里**不要再声明一遍**,
    //   否则就是"隐式声明 + 显式声明"的重复声明, 且端口位宽会截断。
    generate
        if (ILA_EN) begin : g_ila
            ila_0 u_ila (
                .clk    (sys_clk             ),
                .probe0 ({5'b0, meter_dbg_st}),
                .probe1 (meas_dbg_fsm        ),
                .probe2 ({7'b0, wav_hold}    )
            );
        end
    endgenerate

endmodule
