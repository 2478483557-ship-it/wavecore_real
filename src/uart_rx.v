//===========================================================================
// 模块名   : uart_rx
// 功能     : 串口接收 1 个字节 (UART 8N1, 115200) —— uart_tx 的镜像
// 时序(修正版 v1.1) :
//   1. 空闲检测到起始位下降沿
//   2. 等【半位】到起始位中点, 复查仍是低 => 确认真起始位
//   3. 之后每等【一个完整位长(DIV)】采一次 -> 正好踩在每个数据位的中点
//   4. 停止位中点处收工, 输出 rx_done
//   常见错误: 数据位也按半位采 => 采样点落在位的边界(数据切换瞬间),
//      收到的字节全是乱的。本模块 v1.0 就犯过, v1.1 已修正(见 llm #021)。
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.1
//===========================================================================

module uart_rx #(
    parameter DIV = 434        // 50MHz / 115200
)(
    input  wire        clk,     // 系统时钟 50MHz
    input  wire        rst_n,   // 复位, 低有效
    input  wire        rxd,     // 串口接收脚 (CH340: E14)
    output reg  [7:0]  rx_data, // 收到的字节
    output reg         rx_done  // 收完脉冲
);

    localparam HALF = DIV / 2;  // 半个位长

    reg [1:0] state;
    localparam S_IDLE = 2'd0;
    localparam S_HALF = 2'd1;   // 等半位(到达起始位中点)
    localparam S_DATA = 2'd2;   // 采 8 个数据位(每位中点)
    localparam S_STOP = 2'd3;   // 停止位中点收工

    reg [9:0] cnt;              // 位内计时
    reg [2:0] bit_i;            // 当前数据位

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IDLE;
            rx_data <= 8'd0;
            rx_done <= 1'b0;
            cnt     <= 10'd0;
            bit_i   <= 3'd0;
        end
        else begin
            rx_done <= 1'b0;                 // 脉冲默认清 0
            case (state)
                S_IDLE: begin
                    if (!rxd) begin          // 检测到起始位(下降沿)!
                        state <= S_HALF;
                        cnt   <= 10'd0;
                        bit_i <= 3'd0;
                    end
                end
                S_HALF: begin
                    if (cnt == HALF - 1) begin   // 到起始位中点
                        cnt <= 10'd0;
                        if (!rxd) state <= S_DATA;   // 复查仍是低 = 真起始位
                        else      state <= S_IDLE;   // 毛刺, 放弃
                    end
                    else cnt <= cnt + 10'd1;
                end
                S_DATA: begin
                    // 每满【一个完整位长】采一次 = 正好在每个数据位的中点
                    if (cnt == DIV - 1) begin
                        rx_data[bit_i] <= rxd;      // 采中点值
                        cnt <= 10'd0;
                        if (bit_i == 3'd7) state <= S_STOP;
                        else              bit_i <= bit_i + 3'd1;
                    end
                    else cnt <= cnt + 10'd1;
                end
                S_STOP: begin
                    if (cnt == DIV - 1) begin      // 停止位中点收工
                        cnt     <= 10'd0;
                        state   <= S_IDLE;
                        rx_done <= 1'b1;
                    end
                    else cnt <= cnt + 10'd1;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
