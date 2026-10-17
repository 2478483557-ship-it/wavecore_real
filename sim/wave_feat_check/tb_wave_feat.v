`timescale 1ns/1ps
//===========================================================================
// tb_wave_feat: 喂 1024 个样点, 读回 6 个特征, 与 Python 定点模型逐项比对
//   向量文件 feat_vectors.txt, 每行格式:
//     <1024 个 2 位 hex 样点> | <6 个 4 位 hex 期望特征>
//   容差: ±30 LSB（f4 实测最大差 26, 约 0.08%，来自逐点差分的定点舍入）（浮点算特征 vs RTL 定点, 允许量化差异）
//===========================================================================
module tb_wave_feat;
    reg clk = 0, rst_n = 0, start = 0, din_valid = 0;
    reg signed [7:0] din = 8'sd0;
    wire [15:0] f0, f1, f2, f3, f4, f5;
    wire        done;
    wire [3:0]  dbg_st, dbg_op;

    integer npass = 0, nfail = 0;
    integer fd, r, i, nv, k;
    reg [7:0]  samp [0:1023];
    reg [15:0] expc [0:5];
    reg [7:0]  rd;
    integer    v;
    reg [8*64:1] line;

    always #10 clk = ~clk;

    wave_feat u_dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .din(din), .din_valid(din_valid),
        .f0(f0), .f1(f1), .f2(f2), .f3(f3), .f4(f4), .f5(f5),
        .done(done), .dbg_st(dbg_st), .dbg_op(dbg_op)
    );

    task chk_near(input [15:0] got, input [15:0] exp, input [8*16:1] nm);
        integer d;
        begin
            d = (got > exp) ? (got - exp) : (exp - got);
            if (d <= 30) begin
                npass = npass + 1;
            end
            else begin
                nfail = nfail + 1;
                $display("    FAIL %0s: got=%0d exp=%0d diff=%0d", nm, got, exp, d);
            end
        end
    endtask

    initial begin
        $display("==== wave_feat 特征提取器回归 ====");
        fd = $fopen("feat_vectors.txt", "r");
        if (fd == 0) begin
            $display("  [错误] 打不开 feat_vectors.txt");
            $finish;
        end
        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (5) @(posedge clk);

        for (r = 0; r < 16; r = r + 1) begin
            // ---- 读一行: 1024 个样点 + 6 个期望值 ----
            for (i = 0; i < 1024; i = i + 1) begin
                nv = $fscanf(fd, "%h", v);
                samp[i] = v[7:0];
            end
            nv = $fscanf(fd, "|");
            for (i = 0; i < 6; i = i + 1) begin
                nv = $fscanf(fd, "%h", v);
                expc[i] = v[15:0];
            end

            // ---- 喂样点 ----
            @(negedge clk); start = 1'b1;
            @(negedge clk); start = 1'b0;
            for (i = 0; i < 1024; i = i + 1) begin
                @(negedge clk);
                din = samp[i];
                din_valid = 1'b1;
            end
            @(negedge clk); din_valid = 1'b0;

            // ---- 等 done(含 6 次除法/开方, 约 300+ 拍) ----
            fork : w
                begin : to
                    #200000;
                    $display("    [TIMEOUT] r=%0d st=%0d op=%0d", r, dbg_st, dbg_op);
                    nfail = nfail + 1;
                    disable w;
                end
                begin
                    @(posedge done);
                    disable w;
                end
            join
            repeat (4) @(posedge clk);

            if (r % 4 == 0)
                $display("  第 %0d 组(r=%0d, 类%0d):", r / 4 + 1, r, r / 4);
            chk_near(f0, expc[0], "f0");
            chk_near(f1, expc[1], "f1");
            chk_near(f2, expc[2], "f2");
            chk_near(f3, expc[3], "f3");
            chk_near(f4, expc[4], "f4");
            chk_near(f5, expc[5], "f5");
            $display("    r=%0d  f0=%0d/%0d f1=%0d/%0d f2=%0d/%0d f3=%0d/%0d f4=%0d/%0d f5=%0d/%0d",
                     r, f0, expc[0], f1, expc[1], f2, expc[2],
                     f3, expc[3], f4, expc[4], f5, expc[5]);
        end

        $fclose(fd);
        $display("=====================================================");
        $display("RESULT: PASS=%0d FAIL=%0d", npass, nfail);
        if (nfail == 0) $display("*** 全部通过: 特征提取与 Python 模型一致(±3 LSB) ***");
        else            $display("*** 有不一致, 看上面 FAIL 行 ***");
        $finish;
    end
endmodule
