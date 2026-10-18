`timescale 1ns/1ps
//===========================================================================
// tb_spec_avg: 验证 N 帧滑动平均（SH=3, N=8）
//
// 三条场景:
//   1) en=0 直通: 输出应等于输入
//   2) en=1 恒定输入: 收敛到输入值
//   3) en=1 阶跃: 收敛轨迹符合 out = x_new + (x_old-x_new)*(1-1/N)^k
//
// ★ 测试方法上的两个坑（都踩过）:
//   a) 推完一个样点后要留间隔。真实 FFT 每帧顺序扫 bin 0..511, 同一 bin 隔 512 拍
//      才再访一次; 而流水线有 3 拍延迟, 背靠背压同一个地址会读到旧值、累加漏拍。
//   b) **输出只在写入那一拍有效**。流水线对任何 addr 都会算一次
//      (q - q/N + mag_1), 若在 we=0 时去读输出, 拿到的是"用陈旧 mag 硬算"的废值。
//      所以每条断言都要在 push 之后按流水线延迟取输出。
//===========================================================================
module tb_spec_avg;
    localparam SH = 3;
    localparam N  = 8;

    reg clk = 0, rst_n = 0, en = 0, we = 0;
    reg [8:0]  addr = 0;
    reg [16:0] mag  = 0;
    wire [16:0] mag_out;

    integer npass = 0, nfail = 0;
    integer f;
    reg [16:0] last_out;          // 最近一次 push 对应的输出

    always #10 clk = ~clk;

    spec_avg #(.SH(SH)) u_dut (
        .clk(clk), .rst_n(rst_n), .en(en), .we(we),
        .addr(addr), .mag(mag), .mag_out(mag_out)
    );

    // 推入一个样点, 并在流水线延迟后取回对应的输出
    task push(input [8:0] a, input [16:0] m);
        begin
            @(negedge clk); we = 1; addr = a; mag = m;
            @(negedge clk); we = 0;
            repeat (3) @(negedge clk);
            last_out = mag_out;
        end
    endtask

    task chk(input [16:0] got, input [16:0] exp,
             input [8*24:1] nm, input integer tol);
        integer d;
        begin
            d = (got > exp) ? (got - exp) : (exp - got);
            if (d <= tol) npass = npass + 1;
            else begin
                nfail = nfail + 1;
                $display("    FAIL %0s: got=%0d exp=%0d diff=%0d", nm, got, exp, d);
            end
        end
    endtask

    initial begin
        $display("==== spec_avg 验证 (SH=%0d, N=%0d) ====", SH, N);
        repeat (5) @(posedge clk); rst_n = 1; repeat (3) @(posedge clk);

        //---- 场景1: en=0 直通 ----
        en = 0;
        push(9'd0, 17'd1000); chk(last_out, 1000, "直通1000", 0);
        push(9'd0, 17'd5000); chk(last_out, 5000, "直通5000", 0);
        $display("    场景1: 直通 OK");

        //---- 场景2: 恒定 1000, 收敛 ----
        en = 1;
        for (f = 0; f < 60; f = f + 1) push(9'd0, 17'd1000);
        chk(last_out, 1000, "恒定1000收敛", 2);
        $display("    场景2: 恒定输入收敛到 %0d", last_out);

        //---- 场景3: 阶跃 1000 -> 9000 ----
        // 理论: out(k) = 9000 + (1000-9000)*(1-1/8)^k
        //   k=8: 9000 - 8000*0.3436 = 6251
        //   k=20: 9000 - 8000*0.0693 = 8446
        for (f = 0; f < 8; f = f + 1) push(9'd0, 17'd9000);
        chk(last_out, 6251, "阶跃8帧", 80);
        $display("    场景3: 8 帧后 %0d (理论 6251)", last_out);
        // 收敛速度: 每帧残留乘 (1-1/8)。从 6251 到 9000 需约 80 帧才能进 3 LSB。
        for (f = 0; f < 100; f = f + 1) push(9'd0, 17'd9000);
        chk(last_out, 9000, "阶跃后稳定", 3);
        $display("    场景3: 稳定后 %0d", last_out);

        //---- 场景4: 多 bin 互不干扰 ----
        // 复位重来，三个 bin 各自独立收敛
        rst_n = 0; repeat (3) @(posedge clk); rst_n = 1; repeat (3) @(posedge clk);
        en = 1;
        for (f = 0; f < 60; f = f + 1) begin
            push(9'd0, 17'd1000);
            push(9'd1, 17'd2000);
            push(9'd2, 17'd3000);
        end
        push(9'd0, 17'd1000); chk(last_out, 1000, "bin0", 2);
        push(9'd1, 17'd2000); chk(last_out, 2000, "bin1", 2);
        push(9'd2, 17'd3000); chk(last_out, 3000, "bin2", 2);
        $display("    场景4: 三 bin 并行互不干扰");

        $display("=====================================================");
        $display("RESULT: PASS=%0d FAIL=%0d", npass, nfail);
        if (nfail == 0) $display("*** 全部通过 ***");
        else            $display("*** 有失败 ***");
        $finish;
    end
endmodule
