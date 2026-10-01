//===========================================================================
// 模块名   : spec_compress  (幅度谱 8bit 对数压缩, 0x8E 谱帧配套)
// 功能     : 17 位线性幅度(L1 模) -> 8 位对数码
//            y = (b<<4) | frac4 ; b = 最高有效位位置(0..15), frac4 = MSB 下方 4 位
//            每倍频程 16 级 -> 步进约 0.38dB, 动态范围约 96dB, 正好填满 8 位
// 实现     : 纯组合(优先编码 + 移位), 不用 DSP、不用查表, 约 70 LUT
// 对应模型 : hw_analysis/verify_spectrum_frame.py 的 compress()(逐字一致,
//            改这里的公式必须同步改模型, 否则"金标准"就失去意义)
// 作者     : WaveCore 队长 | 2026-09-30 | v1.0
//===========================================================================
module spec_compress (
    input  wire [16:0] mag,     // |re|+|im| (与找峰同一口径), 范围 0..65536
    output reg  [7:0]  y
);

    reg  [4:0]  b;              // 最高有效位位置 0..16
    reg  [31:0] sh;             // 移位中间量(Msb 对齐到 bit15)

    always @* begin
        // ---- 优先编码: 找 mag 的最高有效位 ----
        if      (mag[16]) b = 5'd16;
        else if (mag[15]) b = 5'd15;
        else if (mag[14]) b = 5'd14;
        else if (mag[13]) b = 5'd13;
        else if (mag[12]) b = 5'd12;
        else if (mag[11]) b = 5'd11;
        else if (mag[10]) b = 5'd10;
        else if (mag[9])  b = 5'd9;
        else if (mag[8])  b = 5'd8;
        else if (mag[7])  b = 5'd7;
        else if (mag[6])  b = 5'd6;
        else if (mag[5])  b = 5'd5;
        else if (mag[4])  b = 5'd4;
        else if (mag[3])  b = 5'd3;
        else if (mag[2])  b = 5'd2;
        else if (mag[1])  b = 5'd1;
        else              b = 5'd0;

        if (mag == 17'd0) begin
            y = 8'd0;                                  // log(0) 定义为 0
        end
        else if (b >= 5'd16) begin
            y = 8'hFF;                                 // 极端值饱和(正常用不到)
        end
        else begin
            sh = ({15'b0, mag} << (5'd15 - b));        // 把 MSB 对齐到 bit15
            y  = {b[3:0], sh[14:11]};                  // 4 位指数 + 4 位尾数
        end
    end

endmodule
