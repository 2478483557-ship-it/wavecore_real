//===========================================================================
// 模块名   : timebase  (0x8D 时基档位)
// 功能     : 给"波形 / FFT"三条通路提供 **抽取比 decim** 与 **等效采样率 fs_hz**
//            ad_cap 以 50MHz 节拍更新(见 ad_driver.v) -> fs = 50MHz / decim
// 档位     : sel=0 -> T1: decim=1000  fs=50kHz    (默认; 与 2026-10-01 之前逐位相同)
//            sel=1 -> T2: decim=4000  fs=12.5kHz  (细分辨率: 1024 点 Δf=12.2Hz)
//            sel=2 -> T3: decim=500   fs=100kHz   (展宽: 波形/频谱覆盖 0~50kHz)
// 纪律     : ① 上电/复位必须回到 T1, 保证"默认行为不变";
//            ② 频率换算**只许引用 fs_hz**, 不许再写字面量 50000 (SK-033 / SK-038);
//            ③ decim 下限受 ADC 限制(25MSPS -> 最小 2), 本模块各档都 >= 500, 安全。
// 说明     : 切换档位会改变**观察窗时长** (T = N x decim / 50MHz):
//            T1: 1024x1000 = 20.5ms(波形) / 4096x1000 = 82ms(IP FFT)
//            T2: 81.9ms / 327ms      T3: 10.2ms / 41ms
// 作者     : WaveCore 队长 | 2026-10-01 | v1.0
//===========================================================================
module timebase (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        set,       // 0x8D 生效(1 拍脉冲)
    input  wire [1:0]  sel_in,    // 目标档位 0/1/2
    output reg  [31:0] decim,     // 抽取比
    output reg  [31:0] fs_hz,     // 等效采样率(Hz)
    output reg  [1:0]  sel_out    // 当前档位(供调试/上报)
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            decim   <= 32'd1000;
            fs_hz   <= 32'd50000;
            sel_out <= 2'd0;
        end
        else if (set) begin
            case (sel_in)
                2'd1:    begin decim <= 32'd4000; fs_hz <= 32'd12500;  sel_out <= 2'd1; end
                2'd2:    begin decim <= 32'd500;  fs_hz <= 32'd100000; sel_out <= 2'd2; end
                default: begin decim <= 32'd1000; fs_hz <= 32'd50000;  sel_out <= 2'd0; end
            endcase
        end
    end

endmodule
