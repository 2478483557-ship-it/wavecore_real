//===========================================================================
// 模块名   : cmd_decoder
// 功能     : 按 uart_protocol.md 解析下行命令帧
// 帧格式   : 0x5A 0xA5 | TYPE | LEN_H | LEN_L | PAYLOAD(LEN) | SUM
//           SUM = (TYPE+LEN_H+LEN_L+PAYLOAD) 求和取低 8 位(不含帧头)
// 已支持命令:
//   0x81 切换频率档位   payload=1B(0~3) -> preset_load + preset_val
//   0x85 任意频率设置   payload=4B(小端 Hz) -> arb_load + arb_fcw(P0-1)
//   0x87 第二频率设置   payload=4B(小端 Hz) -> dual_load + dual_fcw(双音, A)
//   0x88 波形选择       payload=1B(0正弦/1方波/2三角) -> wave_sel
//   0x89 触发模式       payload=1B(0自由/1上升/2下降) -> trig_mode
//   0x8B 扫频使能       payload=1B(0停/1扫) -> sweep_en
//   0x8E 幅度谱帧请求   空负载 -> spec_req(1拍脉冲); 触发自研FFT并回 512 点谱帧
//   [0x8D] 时基档位     1B: 0=T1(50k,默认) 1=T2(12.5k) 2=T3(100k) 3=T4(200k) -> tb_set/tb_sel
//   0x8C Vpp电压标定    payload=4B(knL,knH,保留,保留) -> cal_kn
//        小端 16 位 KN = 每 LSB 多少 mV x1024(Q10), 默认 8000(=7.8125mV/LSB)。
//        **KN=1024 是特殊调试值**: 1024>>10=1, 此时上报的 V 字段就是原始 LSB。
//   其它命令暂忽略
// 任意频率换算(P0-1 新知识):
//   fcw = Hz x 2^32 / 50MHz, 里面有个"除以 5000 万"。
//   FPGA 里做除法很费资源, 技巧: 换成乘一个常量再右移——
//   因为 Hz x 2^32 / 5e7 = Hz x (2^32/5e7), 而 2^32/5e7 = 85.89934592
//   把它放大 2^24 倍取整得 1_441_150_920, 于是:
//   fcw = Hz x 1_441_150_920 >> 24   (误差 <0.01%, 远超 1% 验收线)
// 作者     : WaveCore 队长 | 日期: 2026-09-04 | 版本: v2.0
//===========================================================================

module cmd_decoder (
    input  wire        clk,        // 系统时钟 50MHz
    input  wire        rst_n,      // 复位, 低有效
    input  wire [7:0]  rx_byte,    // uart_rx 收到的字节
    input  wire        rx_done,    // uart_rx 收完脉冲
    output reg         preset_load,// 切档命令有效(1 拍脉冲)
    output reg  [1:0]  preset_val, // 目标档位 0~3
    output reg         arb_load,   // 任意频率命令有效(1 拍脉冲)
    output reg  [31:0] arb_fcw,    // 任意频率对应的 fcw
    output reg         dual_load,  // 0x87 第二频率命令有效(1 拍脉冲)
    output reg  [31:0] dual_fcw,   // 第二频率对应的 fcw
    output reg         wave_req,   // 0x83 请求波形(1 拍脉冲)
    output reg  [1:0]  wave_sel,   // 0x88 波形选择: 0=正弦 1=方波 2=三角
    output reg  [1:0]  trig_mode,  // 0x89 触发模式: 0=自由 1=上升 2=下降
    output reg         sf_run,     // 0x8A 自研FFT运行一次(脉冲)
    output reg         sweep_en,   // 0x8B 扫频使能(电平: 1=扫/0=停)
    output reg  [15:0] cal_kn,     // 0x8C 每LSB多少mV x1024 (Q10), 带记忆
    output reg         cal_load,   // 0x8C 标定生效(1拍脉冲, 留给上位机做回执/闪灯)
    output reg         spec_req,   // 0x8E 幅度谱帧请求(1拍脉冲)
    output reg         tb_set,     // [0x8D] 时基档位生效(1拍脉冲)
    output reg  [1:0]  tb_sel,     // [0x8D] 目标档位 0=T1(50k) 1=T2(12.5k) 2=T3(100k) 3=T4(200k)
    output reg         pre_set,    // [0x8F] 预触发档位生效(1拍脉冲)
    output reg  [1:0]  pre_sel,    // [0x8F] 预触发档: 0=0% 1=25% 2=50% 3=75%
    output reg         win_set,    // [0x90] 窗函数档位生效(1拍脉冲)  [10-16 新增]
    output reg  [1:0]  win_sel     // [0x90] 窗函数: 0=矩形 1=Hann 2=Blackman  [10-16 新增]
);

    // 换算常量: round(2^32/5e7 x 2^24)
    localparam [31:0] M = 32'd1_441_150_920;
    // 频率上限(2^32 相位 / 20ns 采样, 建议 <= 12.5MHz 保证 256 点/周期余量)
    localparam [31:0] HZ_MAX = 32'd12_500_000;
    // Vpp 标定默认值: 36.33 mV/LSB x1024 = 37203
    //   [2026-10-02 实测标定] ATK_HS_AD_DA 模块的 AD 输入端量程是 **-5V~+5V**
    //   （模块内部先做“÷5 再加 1V”的衰减/偏置，才送进 AD9280 的 0~2V），
    //   所以 1 个 ADC 计数对应**模块外部输入端**约 36.3mV。
    //   标定数据: 1kHz 方波实测 高 +2.54V / 低 -2.51V (Vpp = 5.05V) <-> 原始计数 139
    //             => KN = round(5050*1024/139) = 37203，满量程约 9.26V(覆盖 ±5V)。
    //   [!] 该值绑定模块上"DA 输出幅度电位器"的当前位置；动了电位器必须重新标定。
    // 注意: 这是"出厂假设值", 真值要用万用表两点法实测后由 0x8C 覆盖
    localparam [15:0] KN_DEF = 16'd37203;

    reg [2:0] st;
    localparam ST_H1 = 3'd0;   // 找 0x5A
    localparam ST_H2 = 3'd1;   // 找 0xA5
    localparam ST_TY = 3'd2;   // TYPE
    localparam ST_LH = 3'd3;   // LEN_H
    localparam ST_LL = 3'd4;   // LEN_L
    localparam ST_PL = 3'd5;   // 负载
    localparam ST_SU = 3'd6;   // SUM

    reg [7:0]  typ_r;          // 暂存 TYPE
    reg [15:0] len_r;          // 负载长度
    reg [7:0]  sum_r;          // 累加校验(不含帧头)
    reg [2:0]  pidx;           // 已收负载字节数
    reg [7:0]  pbuf [0:3];     // 负载缓存(最多 4 字节, 够本协议用)

    // 任意频率计算(组合): 拼 4 字节小端 Hz -> 限幅 -> 乘常量 -> 右移 24
    wire [31:0] hz_raw = {pbuf[3], pbuf[2], pbuf[1], pbuf[0]};
    wire [31:0] hz_cap = (hz_raw > HZ_MAX) ? HZ_MAX : hz_raw;   // 超上限就钳住
    wire [62:0] hz_mul = hz_cap * M;                             // 32x31 位乘法
    wire [31:0] hz_fcw = hz_mul[55:24];                          // >>24 取高 32 位

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st          <= ST_H1;
            preset_load <= 1'b0;
            preset_val  <= 2'd0;
            arb_load    <= 1'b0;
            arb_fcw     <= 32'd0;
            dual_load   <= 1'b0;
            dual_fcw    <= 32'd0;
            wave_sel    <= 2'd0;
            trig_mode   <= 2'd0;
            sf_run      <= 1'b0;
            sweep_en    <= 1'b0;
            wave_req    <= 1'b0;
            cal_load    <= 1'b0;
            win_set     <= 1'b0;
            win_sel     <= 2'd1;      // [10-16] 上电默认 Hann, 与 09-30 起的既有行为一致
            spec_req    <= 1'b0;
            tb_set      <= 1'b0;
            pre_set     <= 1'b0;
            pre_sel     <= 2'd0;               // [0x8F] 上电默认 0% 预触发
            cal_kn      <= KN_DEF;             // 上电即载入实测标定值 37203 (36.33mV/LSB)
            typ_r       <= 8'd0;
            len_r       <= 16'd0;
            sum_r       <= 8'd0;
            pidx        <= 3'd0;
        end
        else begin
            preset_load <= 1'b0;               // 脉冲默认清 0
            arb_load    <= 1'b0;
            dual_load   <= 1'b0;
            wave_req    <= 1'b0;
            sf_run      <= 1'b0;
            cal_load    <= 1'b0;
            spec_req    <= 1'b0;
            tb_set      <= 1'b0;
            pre_set     <= 1'b0;
            if (rx_done) begin
                case (st)
                    ST_H1: begin
                        if (rx_byte == 8'h5A) st <= ST_H2;
                    end
                    ST_H2: begin
                        if      (rx_byte == 8'hA5) st <= ST_TY;
                        else if (rx_byte == 8'h5A)  st <= ST_H2;  // 连续 5A 5A
                        else                        st <= ST_H1;
                    end
                    ST_TY: begin
                        typ_r <= rx_byte;
                        sum_r <= rx_byte;            // SUM 从 TYPE 开始累加
                        st    <= ST_LH;
                    end
                    ST_LH: begin
                        len_r[15:8] <= rx_byte;
                        sum_r <= sum_r + rx_byte;
                        st    <= ST_LL;
                    end
                    ST_LL: begin
                        len_r[7:0] <= rx_byte;
                        sum_r <= sum_r + rx_byte;
                        pidx  <= 3'd0;
                        if (rx_byte > 8'd4)      st <= ST_H1;    // 超长帧丢弃(本协议最大 4 字节负载)
                        else if (rx_byte == 8'd0) st <= ST_SU;    // 无负载
                        else                     st <= ST_PL;
                    end
                    ST_PL: begin
                        pbuf[pidx] <= rx_byte;
                        sum_r <= sum_r + rx_byte;
                        if (pidx == len_r[2:0] - 3'd1) st <= ST_SU;
                        else                           pidx <= pidx + 3'd1;
                    end
                    ST_SU: begin
                        if (rx_byte == sum_r) begin       // 校验通过才执行
                            case (typ_r)
                                8'h81: begin
                                    preset_load <= 1'b1;
                                    preset_val  <= pbuf[0][1:0];
                                end
                                8'h85: begin             // 任意频率
                                    arb_load <= 1'b1;
                                    arb_fcw  <= hz_fcw;
                                end
                                8'h87: begin             // 第二频率(双音)
                                    dual_load <= 1'b1;
                                    dual_fcw  <= hz_fcw;
                                end
                                8'h83: begin             // 请求波形(F2-A)
                                    wave_req <= 1'b1;
                                end
                                8'h88: begin             // 波形选择(0正/1方/2三角)
                                    wave_sel <= pbuf[0][1:0];
                                end
                                8'h89: begin             // 触发模式(0自由/1上升/2下降)
                                    trig_mode <= pbuf[0][1:0];
                                end
                                8'h8A: begin             // 自研FFT: 运行一次
                                    sf_run <= 1'b1;
                                end
                                8'h8B: begin             // 扫频: 1=开始 0=停止
                                    sweep_en <= pbuf[0][0];
                                end
                                8'h8C: begin             // Vpp 电压标定
                                    // 小端拼 16 位: KN = pbuf[1]:pbuf[0]
                                    cal_load <= 1'b1;
                                    cal_kn   <= {pbuf[1], pbuf[0]};
                                end
                                8'h8E: begin             // 幅度谱帧请求(空负载)
                                    spec_req <= 1'b1;
                                end
                                8'h8D: begin             // [0x8D] 时基档位: 0=T1 50k / 1=T2 12.5k / 2=T3 100k / 3=T4 200k
                                    tb_set <= 1'b1;
                                    tb_sel <= pbuf[0][1:0];
                                end
                                8'h8F: begin             // [0x8F] 预触发档: 0=0%/1=25%/2=50%/3=75%
                                    pre_set <= 1'b1;
                                    pre_sel <= pbuf[0][1:0];
                                end
                                8'h90: begin             // [10-16] 窗函数: 0=矩形 1=Hann 2=Blackman
                                    win_set <= 1'b1;
                                    win_sel <= pbuf[0][1:0];
                                end
                                default: ;               // 其余命令暂不支持
                            endcase
                        end
                        st <= ST_H1;
                    end
                    default: st <= ST_H1;
                endcase
            end
        end
    end

endmodule
