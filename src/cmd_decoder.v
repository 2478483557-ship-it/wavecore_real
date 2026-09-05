//===========================================================================
// 模块名   : cmd_decoder
// 功能     : 按 uart_protocol.md 解析下行命令帧
// 帧格式   : 0x5A 0xA5 | TYPE | LEN_H | LEN_L | PAYLOAD(LEN) | SUM
//           SUM = (TYPE+LEN_H+LEN_L+PAYLOAD) 求和取低 8 位(不含帧头)
// 已支持命令:
//   0x81 切换频率档位   payload=1B(0~3) -> preset_load + preset_val
//   0x85 任意频率设置   payload=4B(小端 Hz) -> arb_load + arb_fcw(P0-1)
//   0x87 第二频率设置   payload=4B(小端 Hz) -> dual_load + dual_fcw(双音, A)
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
    output reg  [31:0] dual_fcw    // 第二频率对应的 fcw
);

    // 换算常量: round(2^32/5e7 x 2^24)
    localparam [31:0] M = 32'd1_441_150_920;
    // 频率上限(2^32 相位 / 20ns 采样, 建议 <= 12.5MHz 保证 256 点/周期余量)
    localparam [31:0] HZ_MAX = 32'd12_500_000;

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
            typ_r       <= 8'd0;
            len_r       <= 16'd0;
            sum_r       <= 8'd0;
            pidx        <= 3'd0;
        end
        else begin
            preset_load <= 1'b0;               // 脉冲默认清 0
            arb_load    <= 1'b0;
            dual_load   <= 1'b0;
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
                        if (rx_byte > 8'd4)      st <= ST_H1;    // 超长帧丢弃
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
