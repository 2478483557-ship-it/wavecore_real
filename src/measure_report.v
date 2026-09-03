//===========================================================================
// 模块名   : measure_report
// 功能     : 每次测量结束, 通过串口上报一行结果(M4b)
// 上报格式 : 固定宽度, 方便电脑解析:
//            "F=0100000Hz V=255\r\n"
//            7 位频率(Hz) + 3 位 Vpp, 前导补 0
// 波特率   : 115200, 8N1
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v3.0(极简)
//===========================================================================

module measure_report (
    input  wire        clk,        // 系统时钟 50MHz
    input  wire        rst_n,      // 复位, 低有效
    input  wire        meas_done,  // freq_meter 测量完成脉冲
    input  wire [15:0] freq_cnt,   // 周期计数(频率 = 该值 x100 Hz)
    input  wire [7:0]  vpp,        // 峰峰值
    output wire        uart_txd    // 串口发送脚 (CH340, 达芬奇Pro: D17)
);

    //================ 换算 + BCD ================
    wire [23:0] freq_hz = {8'd0, freq_cnt} * 24'd100;   // 最大 6,553,500

    wire [27:0] freq_bcd;
    wire        freq_done;
    reg         freq_start;
    wire [11:0] vpp_bcd;
    wire        vpp_done;
    reg         vpp_start;

    bin2bcd #(.IN_W(24), .OUT_W(28)) u_b2f (
        .clk(clk), .rst_n(rst_n), .start(freq_start),
        .bin(freq_hz), .bcd(freq_bcd), .done(freq_done) );
    bin2bcd #(.IN_W(8), .OUT_W(12)) u_b2v (
        .clk(clk), .rst_n(rst_n), .start(vpp_start),
        .bin({8'd0, vpp}), .bcd(vpp_bcd), .done(vpp_done) );

    // 取 28bit BCD 里第 idx 组(4bit)的十进制值(0~9)
    function [3:0] d10(input [27:0] v, input [3:0] idx);
        d10 = v[idx*4 +: 4];
    endfunction

    //================ 串口 ================
    reg [7:0] tx_byte;
    reg       tx_start;
    wire      tx_busy;
    uart_tx u_uart (.clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
                    .tx_start(tx_start), .tx_busy(tx_busy), .txd(uart_txd));

    //================ 发送状态机 ================
    reg [2:0] state;
    reg [4:0] idx;          // 报文第几个字节(0~18)
    reg       guard;        // 防重复启动护栏
    wire [7:0] ch = char_at(idx);

    function [7:0] char_at(input [4:0] i);
        case (i)
            5'd0:  char_at = 8'h46;                             // 'F'
            5'd1:  char_at = 8'h3D;                             // '='
            5'd2:  char_at = 8'd48 + d10(freq_bcd, 3'd6);       // 频率最高位(百万位)
            5'd3:  char_at = 8'd48 + d10(freq_bcd, 3'd5);
            5'd4:  char_at = 8'd48 + d10(freq_bcd, 3'd4);
            5'd5:  char_at = 8'd48 + d10(freq_bcd, 3'd3);
            5'd6:  char_at = 8'd48 + d10(freq_bcd, 3'd2);
            5'd7:  char_at = 8'd48 + d10(freq_bcd, 3'd1);
            5'd8:  char_at = 8'd48 + d10(freq_bcd, 3'd0);       // 频率最低位
            5'd9:  char_at = 8'h48;                             // 'H'
            5'd10: char_at = 8'h7A;                             // 'z'
            5'd11: char_at = 8'h20;                             // ' '
            5'd12: char_at = 8'h56;                             // 'V'
            5'd13: char_at = 8'h3D;                             // '='
            5'd14: char_at = 8'd48 + d10({16'd0, vpp_bcd}, 3'd2);
            5'd15: char_at = 8'd48 + d10({16'd0, vpp_bcd}, 3'd1);
            5'd16: char_at = 8'd48 + d10({16'd0, vpp_bcd}, 3'd0);
            5'd17: char_at = 8'h0D;                             // '\r'
            default: char_at = 8'h0A;                           // 5'd18 '\n'
        endcase
    endfunction

    localparam S_WAIT = 3'd0;
    localparam S_CF   = 3'd1;   // 启动频率 BCD
    localparam S_WF   = 3'd2;   // 等频率 BCD
    localparam S_CV   = 3'd3;   // 启动 Vpp BCD
    localparam S_WV   = 3'd4;   // 等 Vpp BCD
    localparam S_SEND = 3'd5;   // 逐字节发送

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= S_WAIT;
            freq_start <= 1'b0;
            vpp_start  <= 1'b0;
            tx_start   <= 1'b0;
            idx    <= 5'd0;
            guard  <= 1'b0;
        end
        else begin
            tx_start   <= 1'b0;     // 脉冲默认清 0
            freq_start <= 1'b0;
            vpp_start  <= 1'b0;

            case (state)
                S_WAIT: if (meas_done) begin
                            freq_start <= 1'b1;
                            state <= S_CF;
                        end
                S_CF:   state <= S_WF;
                S_WF:   if (freq_done) begin
                            vpp_start <= 1'b1;
                            state <= S_CV;
                        end
                S_CV:   state <= S_WV;
                S_WV:   if (vpp_done) begin
                            idx   <= 5'd0;
                            guard <= 1'b0;
                            state <= S_SEND;
                        end
                S_SEND: begin
                    // 护栏: 看到 uart 进入忙, 才放行下一字节
                    if (guard) begin
                        if (tx_busy) guard <= 1'b0;
                    end
                    else if (!tx_busy) begin
                        if (idx == 5'd18) begin          // 19 字节发完
                            state <= S_WAIT;            // 回等待, 等下一次测量
                        end
                        else begin
                            tx_byte <= ch;              // 取当前字符
                            tx_start <= 1'b1;           // 启动发送
                            guard  <= 1'b1;             // 进入护栏
                            idx    <= idx + 5'd1;       // 指向下一个字符
                        end
                    end
                end
                default: state <= S_WAIT;
            endcase
        end
    end

endmodule
