//===========================================================================
// 模块名   : cmd_decoder
// 功能     : 按 uart_protocol.md v1.0 解析下行命令帧(M5a)
// 帧格式   : 0x5A 0xA5 | TYPE | LEN_H | LEN_L | PAYLOAD(LEN) | SUM
//           SUM = (TYPE+LEN_H+LEN_L+PAYLOAD) 求和取低 8 位(不含帧头)
// 已支持命令:
//   0x81 切换频率档位  payload=1B(0~3) -> preset_load 脉冲 + preset_val
// 其余命令(M5b 再实现)当前忽略
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module cmd_decoder (
    input  wire        clk,        // 系统时钟 50MHz
    input  wire        rst_n,      // 复位, 低有效
    input  wire [7:0]  rx_byte,    // uart_rx 收到的字节
    input  wire        rx_done,    // uart_rx 收完脉冲
    output reg         preset_load,// 切档命令有效(1 拍脉冲)
    output reg  [1:0]  preset_val  // 目标档位 0~3
);

    reg [2:0] st;
    localparam ST_H1 = 3'd0;   // 找 0x5A
    localparam ST_H2 = 3'd1;   // 找 0xA5
    localparam ST_TY = 3'd2;   // TYPE
    localparam ST_LH = 3'd3;   // LEN_H
    localparam ST_LL = 3'd4;   // LEN_L
    localparam ST_PL = 3'd5;   // 负载
    localparam ST_SU = 3'd6;   // SUM

    reg [7:0] typ_r;           // 暂存 TYPE
    reg [15:0] len_r;          // 负载长度
    reg [7:0]  sum_r;          // 累加校验(不含帧头)
    reg [2:0]  pidx;           // 已收负载字节数
    reg [7:0]  pbuf [0:3];     // 负载缓存(最多 4 字节, 够本协议用)

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st         <= ST_H1;
            preset_load<= 1'b0;
            preset_val <= 2'd0;
            typ_r      <= 8'd0;
            len_r      <= 16'd0;
            sum_r      <= 8'd0;
            pidx       <= 3'd0;
        end
        else begin
            preset_load <= 1'b0;               // 脉冲默认清 0
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
                        if (rx_byte > 8'd4)      st <= ST_H1;    // 超长帧直接丢弃
                        else if (rx_byte == 8'd0) st <= ST_SU;    // 无负载, 下一个就是 SUM
                        else                     st <= ST_PL;
                    end
                    ST_PL: begin
                        pbuf[pidx] <= rx_byte;
                        sum_r <= sum_r + rx_byte;
                        if (pidx == len_r[2:0] - 3'd1) st <= ST_SU;   // 负载收完
                        else                           pidx <= pidx + 3'd1;
                    end
                    ST_SU: begin
                        // 校验通过才执行命令
                        if (rx_byte == sum_r) begin
                            case (typ_r)
                                8'h81: begin                    // 切档
                                    preset_load <= 1'b1;
                                    preset_val  <= pbuf[0][1:0];
                                end
                                default: ;                       // 其余命令暂不支持
                            endcase
                        end
                        st <= ST_H1;                             // 回找帧头
                    end
                    default: st <= ST_H1;
                endcase
            end
        end
    end

endmodule
