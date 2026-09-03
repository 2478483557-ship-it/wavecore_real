//===========================================================================
// 模块名   : freq_ctrl
// 功能     : 频率档位控制器 - 每按一次按键, 切换一个频率档位
// 档位设计 : 4 档, 按 key0 循环切换:
//            档位0: 100kHz  (亮 1 个灯)
//            档位1: 200kHz  (亮 2 个灯)
//            档位2: 500kHz  (亮 3 个灯)
//            档位3: 1MHz    (亮 4 个灯)
//            LED 亮灯个数 = 档位 + 1, 一眼看出当前在第几档
// 频率控制字计算 : fcw = 目标频率 x 2^32 / 50MHz (见 dds_nco.v 头注释)
// 作者     : WaveCore 队长 | 日期: 2026-09-03 | 版本: v1.0
//===========================================================================

module freq_ctrl (
    input  wire        clk,          // 系统时钟 50MHz
    input  wire        rst_n,        // 复位, 低有效
    input  wire        key_pulse,    // 消抖后的按键脉冲(每按一次来一个)
    input  wire        preset_load,  // 串口命令: 直接设定档位(脉冲)
    input  wire [1:0]  preset_val,   // 串口命令: 目标档位 0~3
    output reg  [31:0] fcw,          // 当前档位对应的频率控制字
    output reg  [3:0]  led           // 档位指示 (亮灯个数 = 档位+1)
);

    reg [1:0] idx;   // 档位编号 0~3 (2bit 就能表示 4 个档位)

    // 档位来源: ①串口命令(绝对设定, 优先) ②按键(循环 +1)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            idx <= 2'd0;
        else if (preset_load)
            idx <= preset_val;               // 串口: 直接跳到指定档
        else if (key_pulse)
            idx <= idx + 2'd1;               // 按键: 循环切档
    end

    // 档位 -> 频率控制字 / LED 亮灯数 (组合逻辑查表, 类似前面 ROM 的思路)
    always @(*) begin
        case (idx)
            2'd0:    begin fcw = 32'd8_589_935;   led = 4'b0001; end  // 100kHz
            2'd1:    begin fcw = 32'd17_179_869;  led = 4'b0011; end  // 200kHz
            2'd2:    begin fcw = 32'd42_949_673;  led = 4'b0111; end  // 500kHz
            default: begin fcw = 32'd85_899_346;  led = 4'b1111; end  // 1MHz
        endcase
    end

endmodule
