//===========================================================================
// 模块名   : uart_tx
// 功能     : 串口发送 1 个字节 (UART 8N1, 默认 460800)
// 时序     : 空闲为高电平; 先发 1 位起始位(0), 再发 8 位数据(低位在前),
//            最后发 1 位停止位(1)。
// 波特率   : 50MHz / 460800 ≈ 108 个时钟发 1 位, 由参数 DIV 控制
// 用法     : 空闲(tx_busy=0)时给 tx_data + tx_start 脉冲, 即可发送
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.1
//===========================================================================

module uart_tx #(
    parameter DIV = 108          // 50MHz / 460800 ≈ 108.5(提速! 改回115200用434)
)(
    input  wire        clk,      // 系统时钟 50MHz
    input  wire        rst_n,    // 复位, 低有效
    input  wire [7:0]  tx_data,  // 要发送的字节(ASCII 码等)
    input  wire        tx_start, // 启动发送(1 个时钟宽的脉冲)
    output reg         tx_busy,  // 1 = 正在发送, 此时别发起新发送
    output reg         txd       // 串口发送脚
);

    reg [9:0]  cnt;              // 波特率分频计数: 每 DIV 个时钟翻转 1 位
    reg [2:0]  bit_cnt;          // 当前发到第几位(0~7)
    reg [1:0]  state;
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IDLE;
            txd     <= 1'b1;     // 空闲必须为高(串口协议要求)
            tx_busy <= 1'b0;
            cnt     <= 10'd0;
            bit_cnt <= 3'd0;
        end
        else begin
            case (state)
                S_IDLE: begin
                    txd     <= 1'b1;
                    tx_busy <= 1'b0;
                    if (tx_start) begin
                        tx_busy <= 1'b1;
                        state   <= S_START;
                        cnt     <= 10'd0;
                    end
                end
                S_START: begin
                    txd <= 1'b0;             // 起始位: 拉低持续 1 个位时间
                    if (cnt == DIV - 1) begin
                        cnt <= 10'd0;
                        state <= S_DATA;
                        bit_cnt <= 3'd0;
                    end
                    else cnt <= cnt + 10'd1;
                end
                S_DATA: begin
                    txd <= tx_data[bit_cnt]; // 按位输出, 低位(bit0)在前
                    if (cnt == DIV - 1) begin
                        cnt <= 10'd0;
                        if (bit_cnt == 3'd7)  // 8 位发完 -> 停止位
                            state <= S_STOP;
                        else
                            bit_cnt <= bit_cnt + 3'd1;
                    end
                    else cnt <= cnt + 10'd1;
                end
                S_STOP: begin
                    txd <= 1'b1;             // 停止位: 拉高 1 个位时间
                    if (cnt == DIV - 1) begin
                        cnt   <= 10'd0;
                        state <= S_IDLE;
                    end
                    else cnt <= cnt + 10'd1;
                end
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
