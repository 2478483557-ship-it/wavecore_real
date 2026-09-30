//===========================================================================
// blk_mem_gen_1 行为级替身(仅用于仿真)
// 真实 IP: 1024 x 32 单口 RAM, 无输出寄存器 -> 读延迟 1 拍
// 本替身严格复刻该行为: 写优先, 输出寄存器 1 拍延迟
//===========================================================================
module blk_mem_gen_1 (
    input  wire        clka,
    input  wire [9:0]  addra,
    input  wire [31:0] dina,
    input  wire        wea,
    output reg  [31:0] douta
);
    reg [31:0] mem [0:1023];
    integer i;
    initial begin
        for (i=0;i<1024;i=i+1) mem[i] = 32'd0;
    end
    always @(posedge clka) begin
        if (wea) mem[addra] <= dina;
        douta <= mem[addra];
    end
endmodule
