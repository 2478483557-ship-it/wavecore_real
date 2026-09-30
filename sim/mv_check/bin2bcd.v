//===========================================================================
// 模块名   : bin2bcd
// 功能     : 二进制 -> BCD(十进制) 转换, 供串口显示用
// 算法     : 加 3 移位法(double dabble), 经典面试/笔试算法:
//            1. 把 BCD 寄存器清零, 二进制数放到另一个移位寄存器
//            2. 重复 n 次(n = 二进制位数):
//               a. BCD 中每一位(每 4 bit 一组)如果 >4 就 +3
//                  (目的是让"左移一位"等价于"乘 2 且不进坏位")
//               b. 整体左移一位, 二进制最高位移入 BCD 最低位
//            完成后 BCD 寄存器就是十进制结果
// 例       : 16bit 最大 65535 -> 需要 5 位十进制 -> BCD 20bit
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module bin2bcd #(
    parameter IN_W  = 16,    // 输入二进制位宽
    parameter OUT_W = 20     // 输出 BCD 位宽(4bit x 十进制位数)
)(
    input  wire               clk,     // 系统时钟
    input  wire               rst_n,   // 复位, 低有效
    input  wire               start,   // 开始转换(脉冲)
    input  wire [IN_W-1:0]    bin,     // 要转换的二进制数
    output wire [OUT_W-1:0]   bcd,     // BCD 结果(转换完成后有效)
    output reg                done     // 转换完成(脉冲)(在 always 里赋值, 必须是 reg)
);

    reg [OUT_W-1:0] bcd_r;             // BCD 移位寄存器
    reg [IN_W-1:0]  bin_r;             // 二进制移位寄存器
    reg [$clog2(IN_W+1)-1:0] cnt;      // 还剩多少位要处理
    reg             busy;

    integer i;

    wire [OUT_W-1:0] bcd_add3;
    genvar g;
    // 对每一组 4bit, 若 >4 则 +3 (组合逻辑一次性算好)
    // (用 generate 展开, 或直接在 always 里 for 循环实现, 这里用 for)
    reg [OUT_W-1:0] bcd_next;

    always @(*) begin
        bcd_next = bcd_r;
        for (i = 0; i < OUT_W/4; i = i + 1) begin
            if (bcd_next[i*4 +: 4] > 4'd4)
                bcd_next[i*4 +: 4] = bcd_next[i*4 +: 4] + 4'd3;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bcd_r <= {OUT_W{1'b0}};
            bin_r <= {IN_W{1'b0}};
            cnt   <= 0;
            busy  <= 1'b0;
            done  <= 1'b0;
        end
        else if (!busy && start) begin
            busy  <= 1'b1;
            bcd_r <= {OUT_W{1'b0}};
            bin_r <= bin;
            cnt   <= IN_W;
            done  <= 1'b0;
        end
        else if (busy) begin
            if (cnt == 0) begin
                busy  <= 1'b0;
                done  <= 1'b1;           // 完成脉冲
            end
            else begin
                // 1) BCD 各组 >4 加 3;  2) 整体左移, 移入 bin 的最高位
                bcd_r <= {bcd_next[OUT_W-2:0], bin_r[IN_W-1]};
                bin_r <= bin_r << 1;
                cnt   <= cnt - 1;
                done  <= 1'b0;
            end
        end
        else
            done <= 1'b0;
    end

    assign bcd = bcd_r;

endmodule
