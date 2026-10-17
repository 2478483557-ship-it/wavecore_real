`timescale 1ns/1ps
//===========================================================================
// wave_nn 回归: 64 条测试向量(每类 16 条), 金标准 = Python 定点模型
//   向量文件 nn_vectors.hex, 每行 7 个 4 位十六进制: f0..f5(特征 Q15) + 期望类别
//===========================================================================
module tb_wave_nn;
    reg clk = 0, rst_n = 0, start = 0;
    reg [15:0] fv [0:5];
    reg [15:0] vec [0:64*7-1];
    wire [1:0] cls;
    wire       done;
    wire [3:0] dbg;
    integer i, npass = 0, nfail = 0;

    always #10 clk = ~clk;                       // 20ns = 50MHz

    wave_nn u_dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .f0(fv[0]), .f1(fv[1]), .f2(fv[2]), .f3(fv[3]), .f4(fv[4]), .f5(fv[5]),
        .cls(cls), .done(done), .dbg_st(dbg)
    );

    initial begin
        $readmemh("nn_vectors.hex", vec);
        $display("==== wave_nn 推理核回归 (64 条向量, 4 类各 16) ====");
        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (5) @(posedge clk);

        for (i = 0; i < 64; i = i + 1) begin
            fv[0] = vec[i*7+0]; fv[1] = vec[i*7+1]; fv[2] = vec[i*7+2];
            fv[3] = vec[i*7+3]; fv[4] = vec[i*7+4]; fv[5] = vec[i*7+5];

            @(negedge clk); start = 1'b1;         // 避开时钟沿, 保证被采到
            @(negedge clk); start = 1'b0;

            fork : w
                begin : to
                    #20000;
                    $display("  [TIMEOUT] i=%0d st=%0d dbg=%0d", i, u_dut.st, dbg);
                    nfail = nfail + 1;
                    disable w;
                end
                begin
                    @(posedge done);
                    disable w;
                end
            join

            if (cls === vec[i*7+6][1:0]) npass = npass + 1;
            else begin
                nfail = nfail + 1;
                $display("  FAIL i=%0d 期望类别=%0d 实测=%0d", i, vec[i*7+6], cls);
            end
        end

        $display("=====================================================");
        $display("RESULT: PASS=%0d  FAIL=%0d", npass, nfail);
        if (nfail == 0) $display("*** 全部通过: RTL 推理与 Python 定点模型逐条一致 ***");
        else            $display("*** 有不一致, 看上面 FAIL 行 ***");
        $finish;
    end
endmodule
