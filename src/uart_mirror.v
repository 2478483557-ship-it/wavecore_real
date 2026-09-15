//===========================================================================
// 模块名   : uart_mirror  (F1 转发口)
// 功能     : 把 FPGA 的串口数据流(文本行 + 波形帧二进制)"原样镜像"给 STM32
//            做法: 嗅探(src_txd) -> 解码成字节 -> 8 深度 FIFO -> 重新编码发送
//            (不侵入现有 measure/fft/wave 三路仲裁, 零改动镜像全部数据)
// 说明     : src/dst 两侧波特率相同(115200-8N1); 1 字节解码+发送延迟 ~87us
// 作者     : WaveCore 队长 | 日期: 2026-09-15 | 版本: v1.0
//===========================================================================

module uart_mirror (
    input  wire clk,
    input  wire rst_n,
    input  wire src_txd,      // 嗅探源: FPGA 最终 uart_txd(三路仲裁后)
    output wire dst_txd       // 镜像输出: 接 STM32 的 RX (P1: N13)
);

    //======== 嗅探接收(等于把自己发的数据再收一遍) ========
    wire [7:0] sniff_byte;
    wire       sniff_done;
    uart_rx u_sniff (
        .clk     (clk),
        .rst_n   (rst_n),
        .rxd     (src_txd),
        .rx_data (sniff_byte),
        .rx_done (sniff_done)
    );

    //======== 发送侧信号(先声明) ========
    reg        tx_start;
    wire       tx_busy;

    //======== 8 深度 FIFO ========
    reg [7:0] fifo [0:7];
    reg [3:0] wr_ptr, rd_ptr, count;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= 4'd0;
            rd_ptr <= 4'd0;
            count  <= 4'd0;
        end
        else begin
            if (sniff_done && count != 4'd8) begin   // 入队(丢弃极端溢出)
                fifo[wr_ptr] <= sniff_byte;
                wr_ptr <= wr_ptr + 4'd1;
                count  <= count + 4'd1;
            end
            if (tx_start && count != 4'd0) begin     // 出队(发送启动时)
                rd_ptr <= rd_ptr + 4'd1;
                count  <= count - 4'd1;
            end
        end
    end
    wire [7:0] tx_data = fifo[rd_ptr];

    //======== 重编码发送 ========
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) tx_start <= 1'b0;
        else        tx_start <= (count != 4'd0) && !tx_busy;   // FIFO 有货且空闲就发
    end

    uart_tx u_out (
        .clk      (clk),
        .rst_n    (rst_n),
        .tx_data  (tx_data),
        .tx_start (tx_start),
        .tx_busy  (tx_busy),
        .txd      (dst_txd)
    );

endmodule
