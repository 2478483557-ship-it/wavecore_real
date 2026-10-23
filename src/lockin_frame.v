//===========================================================================
// 模块名   : lockin_frame
// 功能     : 把锁相放大的一块 I/Q 结果打成二进制帧发出去
//
// 帧格式   : 5A A5 | 03 | 00 10 | I(6B) Q(6B) N(4B) | SUM
//            共 2+1+2+16+1 = 22 字节
//            I/Q 为 48 位有符号，小端(低字节先)，补码
//            N   为 32 位无符号，本块累加的样点数
//
// 为什么用二进制而不是 ASCII : 48 位有符号数转十进制要除法，占资源还慢；
//            而且这些值本身没有物理意义，主机要除以 N 和参考幅度才有意义。
//
// 作者     : WaveCore | 2026-10-23
//===========================================================================
`timescale 1ns / 1ps

module lockin_frame (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               req,       // 0x9B 请求(1 拍脉冲)
    input  wire               lk_busy,   // 其它 TX 通道忙(等它们发完再发, 防穿插)
    input  wire signed [47:0] i_val,
    input  wire signed [47:0] q_val,
    input  wire [31:0]        n_val,
    output wire               uart_txd,
    output wire               lk_active  // 占用 TX 标志
);

    // ---------------- 帧体(22 字节) ----------------
    reg [7:0] body [0:21];
    integer k;
    always @(*) begin
        body[0]  = 8'h5A;
        body[1]  = 8'hA5;
        body[2]  = 8'h03;                      // TYPE
        body[3]  = 8'h00;                      // LEN_H = 16
        body[4]  = 8'h10;                      // LEN_L
        for (k = 0; k < 6; k = k + 1) begin
            body[5  + k] = i_val[k*8 +: 8];    // I, 低字节先
            body[11 + k] = q_val[k*8 +: 8];    // Q
        end
        for (k = 0; k < 4; k = k + 1)
            body[17 + k] = n_val[k*8 +: 8];    // N
        // 校验和：除最后一字节外全部累加取低 8 位
        body[21] = body[0]  + body[1]  + body[2]  + body[3]  + body[4]
                 + body[5]  + body[6]  + body[7]  + body[8]  + body[9]
                 + body[10] + body[11] + body[12] + body[13] + body[14]
                 + body[15] + body[16] + body[17] + body[18] + body[19]
                 + body[20];
    end

    // ---------------- 发送状态机 ----------------
    localparam S_IDLE = 2'd0, S_RUN = 2'd1, S_END = 2'd2;

    reg [1:0]  st;
    reg [4:0]  idx;
    reg        tx_start;
    reg [7:0]  tx_byte;
    wire       tx_busy;
    reg        act;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; idx <= 5'd0;
            tx_start <= 1'b0; tx_byte <= 8'd0; act <= 1'b0;
        end else begin
            tx_start <= 1'b0;
            case (st)
                S_IDLE: begin
                    act <= 1'b0;
                    if (req && !lk_busy) begin
                        act <= 1'b1;
                        idx <= 5'd0;
                        st  <= S_RUN;
                    end
                end
                S_RUN: begin
                    if (!tx_busy && !tx_start) begin
                        tx_byte  <= body[idx];
                        tx_start <= 1'b1;
                        if (idx == 5'd21) st <= S_END;
                        else              idx <= idx + 5'd1;
                    end
                end
                S_END: begin
                    // 等最后一个字节真正发完再释放通道
                    if (!tx_busy && !tx_start) begin
                        act <= 1'b0;
                        st  <= S_IDLE;
                    end
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    uart_tx u_uart (
        .clk     (clk     ),
        .rst_n   (rst_n   ),
        .tx_data (tx_byte ),
        .tx_start(tx_start),
        .tx_busy (tx_busy ),
        .txd     (uart_txd)
    );

    assign lk_active = act;

endmodule
