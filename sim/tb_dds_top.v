//===========================================================================
// 测试文件 : tb_dds_top
// 功能     : DDS M1 仿真测试台 - 验证 NCO + 正弦 ROM 输出的频率是否正确
// 测试方案 : 给 fcw = 85899346 (理论输出 1MHz @ 50MHz 采样),
//            数 50000 个时钟内"相位累加器溢出"了几次 = 输出了几个正弦周期,
//            期望约 1000 个周期 (50000 时钟 / 每周期 50 时钟)。
// 作者     : WaveCore 队长 | 日期: 2026-09-02 | 版本: v1.0
//===========================================================================

`timescale 1ns/1ps

module tb_dds_top;

    // ---- 给被测模块的信号 ----
    reg         clk;         // 时钟
    reg         rst_n;       // 复位, 低有效
    reg  [31:0] fcw;         // 频率控制字
    wire [7:0]  sine_out;    // 数字正弦输出

    // 1MHz 输出对应的频率控制字 (计算见 dds_nco.v 头部注释)
    localparam FCW_1M = 32'd85_899_346;

    // ---- 被测模块(DUT) ----
    dds_top u_dut (
        .sys_clk   (clk      ),
        .sys_rst_n (rst_n    ),
        .fcw       (fcw      ),
        .sine_out  (sine_out )
    );

    // 借看内部信号: 相位累加器(用它数"走完了几个周期")
    wire [31:0] phase = u_dut.u_nco.phase_acc;

    // ---- 时钟: 50MHz => 周期 20ns ----
    initial clk = 1'b0;
    always #10 clk = ~clk;

    // ---- 周期计数器: 检测 phase 回绕(数值从大变小 = 溢出一次) ----
    reg [31:0] phase_prev;
    reg [31:0] cycle_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase_prev <= 32'd0;
            cycle_cnt  <= 32'd0;
        end
        else begin
            if (phase < phase_prev)          // 相位回绕 = 完成一个正弦周期
                cycle_cnt <= cycle_cnt + 1'b1;
            phase_prev <= phase;
        end
    end

    // ---- 时钟计数器: 用来确定测试窗口长度 ----
    reg [31:0] clk_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) clk_cnt <= 32'd0;
        else        clk_cnt <= clk_cnt + 1'b1;
    end

    // ---- 主测试流程 ----
    initial begin
        // $display 用英文, 避免控制台中文乱码
        $display("============================================");
        $display("  DDS M1 test: NCO + Sine ROM");
        $display("  fcw = %0d (expect 1MHz @ 50MHz clk)", FCW_1M);
        $display("============================================");

        // 1. 复位: 保持 5 个时钟
        rst_n = 1'b0;
        fcw   = 32'd0;
        repeat (5) @(posedge clk);

        // 2. 释放复位, 给 1MHz 控制字
        rst_n = 1'b1;
        fcw   = FCW_1M;

        // 3. 跑满 50000 个时钟(对应 1ms 仿真时间)
        wait (clk_cnt == 32'd50000);

        // 4. 判定: 50000 个时钟应完成约 1000 个正弦周期
        if (cycle_cnt >= 997 && cycle_cnt <= 1003)
            $display("PASS: cycles = %0d (expect ~1000)", cycle_cnt);
        else
            $display("FAIL: cycles = %0d (expect ~1000)", cycle_cnt);

        $finish;
    end

    // ---- 辅助: 打印前几个样点, 方便对照 ----
    integer i;
    initial begin
        wait (rst_n == 1'b1);
        for (i = 0; i < 8; i = i + 1) begin
            #1000;    // 每 1000ns 打印一次
            $display("sample@%0tns: sine_out = %0d", $time, sine_out);
        end
    end

endmodule
