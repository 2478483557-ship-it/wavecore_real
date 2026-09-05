//===========================================================================
// 模块名   : freq_ctrl
// 功能     : 频率控制 - 按键档位 + 串口命令(P0-1: 任意频率)
// 三种设定来源(互不打架):
//   1. 按键 key0    : 在 4 个预设档位间循环(100k/200k/500k/1M)
//   2. 串口 0x81    : 直接跳到某个预设档位(0~3)
//   3. 串口 0x85    : 输入任意频率(Hz) -> 换算成 fcw, 输出该频率!
// 频率控制字计算 : fcw = 目标频率 x 2^32 / 50MHz (见 dds_nco.v 头注释)
// LED 指示:
//   - 预设档位模式: 亮灯个数 = 档位+1
//   - 任意频率模式: 4 灯全亮(提示"当前是自定义频率, 非预设档")
// 作者     : WaveCore 队长 | 日期: 2026-09-04 | 版本: v2.0
//===========================================================================

module freq_ctrl (
    input  wire        clk,          // 系统时钟 50MHz
    input  wire        rst_n,        // 复位, 低有效
    input  wire        key_pulse,    // 按键脉冲(循环档位)
    input  wire        preset_load,  // 串口 0x81: 设定预设档位(脉冲)
    input  wire [1:0]  preset_val,   // 目标预设档位 0~3
    input  wire        arb_load,     // 串口 0x85: 任意频率生效(脉冲)
    input  wire [31:0] arb_fcw,      // 任意频率对应的 fcw(已在 cmd_decoder 算好)
    output wire [31:0] fcw,          // 输出给 NCO 的频率控制字
    output wire [3:0]  led           // LED 指示
);

    reg [1:0]  idx;          // 预设档位编号 0~3
    reg        arb_mode;     // 1 = 自定义频率模式
    reg [31:0] fcw_arb;      // 自定义频率的 fcw(锁存)

    // ---- 模式与档位状态 ----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            idx      <= 2'd0;
            arb_mode <= 1'b0;
            fcw_arb  <= 32'd0;
        end
        else begin
            if (arb_load) begin
                // 任意频率命令: 锁存 fcw 并切到自定义模式
                fcw_arb  <= arb_fcw;
                arb_mode <= 1'b1;
            end
            else if (preset_load) begin
                idx      <= preset_val;   // 串口指定预设档
                arb_mode <= 1'b0;         // 回到预设模式
            end
            else if (key_pulse) begin
                idx      <= idx + 2'd1;   // 按键循环切档
                arb_mode <= 1'b0;         // 回到预设模式
            end
        end
    end

    // ---- 输出: 预设档查表 or 自定义 fcw ----
    reg [31:0] preset_fcw;   // 在 always 里赋值 => 必须 reg(不是 wire!)
    reg [3:0]  preset_led;
    always @(*) begin
        case (idx)
            2'd0:    begin preset_fcw = 32'd8_589_935;  preset_led = 4'b0001; end  // 100kHz
            2'd1:    begin preset_fcw = 32'd17_179_869; preset_led = 4'b0011; end  // 200kHz
            2'd2:    begin preset_fcw = 32'd42_949_673; preset_led = 4'b0111; end  // 500kHz
            default: begin preset_fcw = 32'd85_899_346; preset_led = 4'b1111; end  // 1MHz
        endcase
    end
    assign fcw = arb_mode ? fcw_arb   : preset_fcw;
    assign led = arb_mode ? 4'b1111   : preset_led;

endmodule
