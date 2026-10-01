//===========================================================================
// blk_mem_gen_0 行为级替身(仅用于 sim/board_elab 整顶层精化检查)
// 真实 IP: 1024 x 8 单口 RAM, 无输出寄存器 -> 读延迟 1 拍
// 本替身只保证端口名/位宽/读延迟一致, 不做任何花哨行为。
//===========================================================================
module blk_mem_gen_0 (
    input  wire       clka,
    input  wire [9:0] addra,
    input  wire [7:0] dina,
    input  wire       wea,
    output reg  [7:0] douta
);
    reg [7:0] mem [0:1023];
    integer i;
    initial begin
        for (i = 0; i < 1024; i = i + 1) mem[i] = 8'd0;
    end
    always @(posedge clka) begin
        if (wea) mem[addra] <= dina;
        douta <= mem[addra];
    end
endmodule
