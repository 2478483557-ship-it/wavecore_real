//===========================================================================
// 模块名   : wave_nn  (波形识别神经网络推理核)
// 功能     : 6 特征 -> 16 隐层(ReLU) -> 4 类, 全定点, 串行 MAC 实现
// 权重     : src/nn_w1.hex(6x16) / nn_b1.hex(16) / nn_w2.hex(16x4) / nn_b2.hex(4)
//            由 hw_analysis/train_wave_nn.py 训练+量化导出(测试集准确率 94%)
// 数据口径 : 特征 Q15(0..32767); 权重 int16; 移位 SH1/SH2 见 nn_meta.json
//            hq = clip(((Σ f·W1) >> SH1) + b1, 0, Q)      -- relu(pre + b1)
//            oq = ((Σ h·W2) >> SH2) + b2                  -- argmax 取类
// 时序     : 一次推理 ~166 拍(16*6 + 4*16 + 若干), 相对一帧 20ms(100 万拍)可忽略
// 作者     : WaveCore 队长 | 日期: 2026-10-17
//===========================================================================
module wave_nn #(
    parameter SH1 = 14,        // 层间移位(与 nn_meta.json 一致, 改权重必须同步改)
    parameter SH2 = 11
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,        // 1 拍脉冲: 开始一次推理
    input  wire [15:0] f0, f1, f2, f3, f4, f5,   // 6 个特征(Q15, 0..32767)
    output reg  [1:0]  cls,          // 0=正弦 1=方波 2=三角 3=其他
    output reg         done,         // 推理完成(1 拍)
    output reg  [3:0]  dbg_st
);
    localparam Q = 16'sd32767;
    localparam S_IDLE = 4'd0, S_L1 = 4'd1, S_L1W = 4'd2,
               S_L2 = 4'd3, S_L2W = 4'd4, S_ARG = 4'd5, S_DONE = 4'd6;

    reg [3:0]  st;
    reg [3:0]  j;                       // 隐层单元下标 0..15
    reg [4:0]  k;                       // 特征下标 0..5 / 隐层下标 0..15
    reg [1:0]  c;                       // 输出类下标 0..3
    reg signed [39:0] acc;              // 累加器: 6*(32767*32767) ~= 6.4e9 > 32 位, 必须放宽
    // [10-17 修复·关键] 必须声明成 **signed**!
    //   原写成 reg [15:0](无符号), 而 w1/w2 是有符号 -> Verilog 规定
    //   "有一个操作数无符号则整体按无符号算", 于是**负权重全被当成巨大正数**,
    //   推理结果自然全错(实测 64 条只对 16 条)。值本身是 0..32767, 用 signed 表示无损。
    reg signed [15:0] feat [0:5];
    reg signed [15:0] hmem [0:15];      // 隐层激活(已定标到 0..Q)
    reg signed [39:0] omax;
    reg [1:0]  argmax;

    // ---- 权重 ROM(综合: $readmemh 工程绝对路径; 仿真用同目录替身) ----
    reg signed [15:0] w1 [0:95];        // [k*16 + j]  行主序
    reg signed [15:0] b1 [0:15];
    reg signed [15:0] w2 [0:63];        // [j*4 + c]
    reg signed [15:0] b2 [0:3];
    initial begin
        $readmemh("D:/Verilog_project/wavecore/src/nn_w1.hex", w1);
        $readmemh("D:/Verilog_project/wavecore/src/nn_b1.hex", b1);
        $readmemh("D:/Verilog_project/wavecore/src/nn_w2.hex", w2);
        $readmemh("D:/Verilog_project/wavecore/src/nn_b2.hex", b2);
    end

    // 第1层预激活(纯组合, 用 wire 承接以便位选)
    wire signed [39:0] pre1 = (acc >>> SH1) + b1[j[3:0]];
    wire signed [39:0] ov2  = (acc >>> SH2) + b2[c];      // 第2层某类的输出
    // 说明: 乘法都写在下面的状态机里(用的是阻塞式下标索引), 这里不再另立 wire。
    //   第1层: feat[k] * w1[k*16 + j]      第2层: hmem[k] * w2[k*4 + c]

    integer ii;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; j <= 4'd0; k <= 5'd0; c <= 2'd0; acc <= 40'sd0;
            cls <= 2'd3; done <= 1'b0; dbg_st <= 4'd0;
            omax <= 40'sd0; argmax <= 2'd0;
            for (ii = 0; ii < 16; ii = ii + 1) hmem[ii] <= 16'd0;
        end
        else begin
            done <= 1'b0;
            dbg_st <= st;
            case (st)
                S_IDLE: begin
                    if (start) begin
                        feat[0]<=f0; feat[1]<=f1; feat[2]<=f2;
                        feat[3]<=f3; feat[4]<=f4; feat[5]<=f5;
                        j <= 4'd0; k <= 5'd0; acc <= 40'sd0;
                        st <= S_L1;
                    end
                end
                // ---- 第1层: 每个隐层单元累加 6 个特征的乘积 ----
                S_L1: begin
                    if (k < 5'd6) begin
                        acc <= acc + (feat[k[2:0]] * w1[k[2:0]*16 + j[3:0]]);
                        k <= k + 5'd1;
                    end
                    else begin
                        // relu((acc >> SH1) + b1), 并夹到 [0, Q]
                        //   注意: 不能写 ((expr))[15:0] —— Verilog 不允许直接对表达式位选,
                        //   必须先用 wire 承接(第一次就是这么报的错)。
                        if (pre1 > 40'sd32767)      hmem[j[3:0]] <= Q;
                        else if (pre1 < 40'sd0)     hmem[j[3:0]] <= 16'd0;
                        else                        hmem[j[3:0]] <= pre1[15:0];
                        k <= 5'd0; acc <= 40'sd0;
                        if (j == 4'd15) begin c <= 2'd0; omax <= 40'sd0; argmax <= 2'd0; st <= S_L2; end
                        else begin j <= j + 4'd1; st <= S_L1; end
                    end
                end
                // ---- 第2层: 每个类累加 16 个隐层输出的乘积, 顺便取 argmax ----
                S_L2: begin
                    if (k < 5'd16) begin
                        acc <= acc + (hmem[k[3:0]] * w2[k[3:0]*4 + c]);
                        k <= k + 5'd1;
                    end
                    else begin
                        // [10-17 修复] omax 原来初始化成 0 -> **负的输出永远赢不了**,
                        //   而输出层出现负值是常态(Python 的 argmax 不受此影响, 所以只在这里错)。
                        //   改法: 第 0 类无条件先占位, 之后才比较。
                        if (c == 2'd0) begin
                            omax   <= ov2;
                            argmax <= 2'd0;
                        end
                        else if (ov2 > omax) begin
                            omax   <= ov2;
                            argmax <= c;
                        end
                        acc <= 40'sd0; k <= 5'd0;
                        if (c == 2'd3) st <= S_ARG;
                        else begin c <= c + 2'd1; st <= S_L2; end
                    end
                end
                S_ARG: begin
                    cls <= argmax; done <= 1'b1; st <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
