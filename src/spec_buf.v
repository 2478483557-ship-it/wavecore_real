//===========================================================================
// 模块名   : spec_buf  (512 x 8bit 幅度谱缓存, 0x8E 谱帧配套)
// 功能     : 写口 = 自研FFT 扫描第 0 趟写入压缩幅度(每帧全量重写);
//            读口 = spec_frame 发送状态机顺序读出, 位序与 bin 号一一对应
// 存储     : 分布式 RAM (LUTRAM), **显式 ram_style="distributed"**
//   为什么用 LUTRAM 而不是 BRAM:
//     读口是异步读(组合输出)。7 系列 BRAM 不支持异步读 —— 若标 "block"
//     会被工具忽略并退化成触发器阵列(就是 f_ram 踩过的那个坑, SK-029)。
//     512x8 = 4Kb, 分布式 RAM 约 130 LUT, 相对当前 69% 的 LUT 余量可忽略。
//   ★ 改完务必核对资源报告: 确认没有大量 FDRE 被"凭空"吃掉。
// 作者     : WaveCore 队长 | 2026-09-30 | v1.0
//===========================================================================
module spec_buf (
    input  wire        clk,
    input  wire        we,
    input  wire [8:0]  waddr,
    input  wire [7:0]  wdata,
    input  wire [8:0]  raddr,
    output wire [7:0]  rdata
);

    (* ram_style = "distributed" *) reg [7:0] mem [0:511];

    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
    end

    assign rdata = mem[raddr];

endmodule
