//===========================================================================
// 模块名   : div_restore
// 功能     : 无符号恢复余数除法器 (num / den = q, 余数丢弃)
// 算法     : 小学竖式除法的二进制版——每拍把被除数最高位"滚"进余数:
//            t = 旧余数x2 + 被除数最高位, 若 t >= 除数: t-=除数, 商位=1
// 约束     : 除数 den 必须 < 2^(D-1) (保证 t < 2^D 不溢出)
// 时序     : start 拉 1 拍开始, N 拍后 done 脉冲, q 有效
// 注意     : 不能出现"先整体移位又单独赋 rem"的写法(非阻塞赋值会互相覆盖)
// 作者     : WaveCore 队长 | 日期: 2026-09-05 | 版本: v1.1
//===========================================================================

module div_restore #(
    parameter N = 32,     // 被除数位宽
    parameter D = 25      // 余数/除数位宽(需保证 den < 2^(D-1))
)(
    input  wire             clk,     // 系统时钟
    input  wire             rst_n,   // 复位
    input  wire             start,   // 开始(脉冲)
    input  wire [N-1:0]     num,     // 被除数
    input  wire [D-1:0]     den,     // 除数(不能为 0)
    output reg  [N-1:0]     q,       // 商
    output reg              done     // 完成(脉冲)
);

    reg [N-1:0] dvd;             // 被除数移位寄存器(每次取最高位)
    reg [D-1:0] rem;             // 余数寄存器
    reg [5:0]   n;               // 剩余位数计数(0~32)
    reg         busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dvd  <= {N{1'b0}};
            rem  <= {D{1'b0}};
            q    <= {N{1'b0}};
            n    <= 6'd0;
            busy <= 1'b0;
            done <= 1'b0;
        end
        else begin
            done <= 1'b0;
            if (!busy && start) begin
                busy <= 1'b1;
                dvd  <= num;
                rem  <= {D{1'b0}};
                q    <= {N{1'b0}};
                n    <= N;
            end
            else if (busy) begin
                if (n == 6'd0) begin
                    busy <= 1'b0;
                    done <= 1'b1;              // N 拍完成
                end
                else begin
                    // 候选余数 = 旧余数<<1 | 被除数最高位 (一位竖式)
                    if ({rem[D-2:0], dvd[N-1]} >= den) begin
                        rem <= {rem[D-2:0], dvd[N-1]} - den;  // 够减
                        q   <= {q[N-2:0], 1'b1};               // 商位 1
                    end
                    else begin
                        rem <= {rem[D-2:0], dvd[N-1]};         // 不够减
                        q   <= {q[N-2:0], 1'b0};               // 商位 0
                    end
                    dvd <= dvd << 1;
                    n   <= n - 6'd1;
                end
            end
        end
    end

endmodule
