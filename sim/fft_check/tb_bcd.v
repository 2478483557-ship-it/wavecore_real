`timescale 1ns/1ps
module tb_bcd;
    reg clk=0, rst_n=0, start=0;
    reg [23:0] bin;
    wire [27:0] bcd; wire done;
    always #10 clk=~clk;
    bin2bcd #(.IN_W(24), .OUT_W(28)) u (
        .clk(clk), .rst_n(rst_n), .start(start), .bin(bin), .bcd(bcd), .done(done));
    task t(input [23:0] v);
        begin
            bin = v; start = 1'b1; @(posedge clk); start = 1'b0;
            @(posedge done); #1;
            $display("  in=%0d (0x%06X)  ->  bcd=0x%07X  = %0d%0d%0d%0d%0d%0d%0d",
                     v, v, bcd,
                     bcd[27:24], bcd[23:20], bcd[19:16], bcd[15:12],
                     bcd[11:8], bcd[7:4], bcd[3:0]);
            repeat(3) @(posedge clk);
        end
    endtask
    initial begin
        repeat(5) @(posedge clk); rst_n=1; repeat(5) @(posedge clk);
        $display("=== 期望 7 位能表示的最大值 9999999 ===");
        t(24'd563600);      // 用户看到的稳定值
        t(24'hD00000 + 24'd0);        // 我的 st=0 编码
        t(24'hD00000 + 24'd19*4096);  // 我的 st=19 编码
        t(24'd1249744);     // 修正后的编码(st=19,flags=0x12)
        $finish;
    end
endmodule
