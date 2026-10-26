//===========================================================================
// tb_report_mv —— 测量上报帧"整帧字节级"回归 (measure_report v3.3)
//
// 用法: bash run_mv_check.sh
//
// 测什么:
//   把 meas_done 打一拍, 然后**用 uart_rx 把 FPGA 发出来的串口流原样解回来**,
//   逐字节跟"期望字符串"比对。场景:
//     S0  复位后第一帧: 显式断言 V/D/W 为 0 (3 窗中值的暖机特性)
//     S1  1000Hz / 139LSB / KN=8000, 稳态 -> V=1085, D=050.0, W=00500, TY=1
//     S2  同 S1 但 KN=1024               -> V=0139 (原始 LSB 透传模式)
//     S3  12345Hz / 255LSB / KN=8000, 稳态 -> V=1992, D=123.4, W=12345, TY=0
//     S4  TY 闸门活性: 帧中途改频率       -> F 仍是旧值, 但 TY 必须变 3
//
// 为什么要"先暖机再比"（重要，别删）:
//   measure_report 里 V/D/W 都过了一遍 **3 窗中值**(med8/med16/med20)抗噪。
//   中值的性质决定: 复位后第一帧历史槽是 0, 于是 med(139,0,0)=0
//   → 上电后**前两帧**的 V/D/W 会显示 0。这是**抗噪换来的代价**, 不是 bug。
//   所以 S1~S4 都先打 2 拍把中值槽填满, 再取第 3 帧比对(测稳态);
//   首帧的暖机行为单独用 S0 显式断言, 免得它被"暖机"这一步悄悄掩盖掉。
//   [!] 由此推出一条使用结论: **改波形(0x88)/改频率(0x85)后, V/D/W 有 2 帧
//      (约 20ms) 滞后**; 改 KN(0x8C) 则是立刻生效(mv 只做组合换算)。
//
// 为什么值得写:
//   v3.3 把 V 字段从 3 位改成 4 位, 后面所有字符的**下标全部后移一位**。
//   下标错一位 → 整帧少发/多发/串位, 板子上只看到"读数莫名其妙"。
//   靠看波形很难发现, 靠逐字节比对一拍就现原形。
//   期望值不是复制 RTL 的 case 表, 而是**用整数除法独立算一遍**
//   (再与 oracle.py 的 Python 复算交叉核对)。
//
// 关于 TY 闸门(2026-09-30 澄清: 本 TB 第一版把它建模错了):
//   RTL 里 prev_f 在 S_WAIT **当场**被赋成 freq_hz, 所以闸门比较的是
//   "本帧开始时的频率" vs "此刻(发字符时)的频率" —— 即**帧内是否变了**,
//   而不是"和上一帧比变没变"。频率稳定时二者相等 → 永远判为可信。
//   于是 F 行显示的频率(锁在 bin2bcd 里)与 TY 的判断可以来自不同时刻,
//   这正是 S4 要测的东西。
//
// 字节布局(46 字节, 下标 0..45):
//   0  F    1  =    2..8 频率(7位)   9  H    10 z   11 ' ' 12 V   13 =
//   14..17 mV(4位)   18 CR  19 LF
//   20 D    21 =    22..24 占空比整数 25 .    26 小数 27 %   28 ' '
//   29 W    30 =    31..35 脉宽(5位)  36 u    37 s    38 CR  39 LF
//   40 T    41 Y    42 =             43 类型 44 CR  45 LF
//
// 作者     : WaveCore 队长 | 日期: 2026-09-30
//===========================================================================
`timescale 1ns / 1ps

module tb_report_mv;

    reg clk = 0, rst_n = 0;
    always #10 clk = ~clk;              // 20ns = 50MHz

    // ---------------- 被测输入 ----------------
    reg  [23:0] freq_hz   = 24'd1000;
    reg  [7:0]  vpp       = 8'd139;
    reg  [15:0] duty_x10  = 16'd500;
    reg  [19:0] width_us  = 20'd500;
    reg  [1:0]  wave_type = 2'd1;
    reg  [15:0] cal_kn    = 16'd8000;
    reg         meas_done = 1'b0;

    wire txd, busy;
    wire [7:0] dbg_fsm;

    measure_report dut (
        .clk(clk), .rst_n(rst_n),
        .meas_done(meas_done), .freq_hz(freq_hz), .vpp(vpp),
        .meas_done2(1'b0), .duty_x10(duty_x10), .width_us(width_us),
        .uart_txd(txd), .wave_type(wave_type), .meas_busy(busy),
        .ext_hold(1'b0), .dbg_fsm(dbg_fsm),
        .dbg_h_tick(32'd0), .dbg_p_tick(32'd0),
        .cal_kn(cal_kn)
    );

    // ---------------- 把串口流解回来(与上位机同一套路) ----------------
    wire [7:0] rb;  wire rd;
    uart_rx #(.DIV(108)) u_rx (
        .clk(clk), .rst_n(rst_n), .rxd(txd), .rx_data(rb), .rx_done(rd)
    );

    reg [7:0] rxbuf [0:63];
    integer   n = 0;
    always @(posedge clk) if (rd) begin
        if (n < 64) rxbuf[n] = rb;
        n = n + 1;
    end

    // ---------------- 期望帧(用整数除法独立生成) ----------------
    reg [7:0] exp [0:45];
    integer   dv, wv, tv, mv, fd;
    integer   k, w;

    function integer p10(input integer e);   // 10^e
        integer r, i;
        begin
            r = 1;
            for (i = 0; i < e; i = i + 1) r = r * 10;
            p10 = r;
        end
    endfunction

    // f_show = 写进 F 字段的频率(= 帧开始时的频率, bin2bcd 已锁存)
    // f_live = 发字符那一刻的 freq_hz (只影响 TY 闸门)
    task build_expect(input integer f_show, input integer f_live, input integer ty_in);
        begin
            dv = duty_x10;  wv = width_us;
            mv = (vpp * cal_kn) >> 10;    // 与 vpp_mv 同公式, 但用整数独立算
            if (mv > 9999) mv = 9999;

            // TY 闸门(与 RTL 同语义): 频率 >25kHz, 或帧内频率变化过大 -> "其他(3)"
            tv = ty_in;
            fd = f_live - f_show;
            if (fd < 0) fd = -fd;
            if (f_show > 25000) tv = 3;
            else if (f_show != 0 && fd > (f_show / 64 + 16)) tv = 3;

            // 第 1 行
            exp[0] = "F"; exp[1] = "=";
            for (k = 0; k < 7; k = k + 1)
                exp[2 + k] = 8'h30 + ((f_show / p10(6 - k)) % 10);
            exp[9] = "H"; exp[10] = "z"; exp[11] = " "; exp[12] = "V"; exp[13] = "=";
            for (k = 0; k < 4; k = k + 1)
                exp[14 + k] = 8'h30 + ((mv / p10(3 - k)) % 10);
            exp[18] = 8'h0D; exp[19] = 8'h0A;
            // 第 2 行
            exp[20] = "D"; exp[21] = "=";
            exp[22] = 8'h30 + ((dv / 1000) % 10);
            exp[23] = 8'h30 + ((dv / 100)  % 10);
            exp[24] = 8'h30 + ((dv / 10)   % 10);
            exp[25] = ".";
            exp[26] = 8'h30 + (dv % 10);
            exp[27] = "%"; exp[28] = " "; exp[29] = "W"; exp[30] = "=";
            for (k = 0; k < 5; k = k + 1)
                exp[31 + k] = 8'h30 + ((wv / p10(4 - k)) % 10);
            exp[36] = "u"; exp[37] = "s"; exp[38] = 8'h0D; exp[39] = 8'h0A;
            // 第 3 行
            exp[40] = "T"; exp[41] = "Y"; exp[42] = "=";
            exp[43] = 8'h30 + tv;
            exp[44] = 8'h0D; exp[45] = 8'h0A;
        end
    endtask

    // ---------------- 逐字节打印与比对 ----------------
    integer fail = 0;
    task dump_and_cmp(input integer tag);
        integer i, bad;
        begin
            $write("场景%0d 收到: ", tag);
            for (i = 0; i < n; i = i + 1) begin
                if (rxbuf[i] == 8'h0D)      $write("<CR>");
                else if (rxbuf[i] == 8'h0A) $write("<LF>\n");
                else                        $write("%c", rxbuf[i]);
            end

            if (n != 46) begin
                fail = fail + 1;
                $display("           [FAIL] 长度=%0d, 期望 46", n);
            end
            else begin
                bad = 0;
                for (i = 0; i < 46; i = i + 1) begin
                    if (rxbuf[i] !== exp[i]) begin
                        bad = bad + 1;
                        $display("           [DIFF] 第 %0d 字节: 收到 '%c', 期望 '%c'",
                                 i,
                                 (rxbuf[i] >= 32) ? rxbuf[i] : ".",
                                 (exp[i]    >= 32) ? exp[i]    : ".");
                    end
                end
                if (bad == 0) $display("           [PASS] 长度 46, 逐字节一致");
                else begin fail = fail + 1; $display("           [FAIL] 有 %0d 个字节不同", bad); end
            end
        end
    endtask

    // 打一拍 meas_done 并收完整帧(不比对)
    task do_frame;
        begin
            n = 0;
            @(posedge clk);
            meas_done = 1'b1;  @(posedge clk);
            meas_done = 1'b0;
            w = 0;
            while (n < 46 && w < 200000) begin @(posedge clk); w = w + 1; end
            @(posedge clk);
            repeat (300) @(posedge clk);
        end
    endtask

    // 暖机: 连打 2 拍, 把 V/D/W 的 3 窗中值槽填满
    task prime;
        begin
            do_frame; do_frame;
        end
    endtask

    // 稳态场景: 暖机 -> 设期望 -> 打一拍收帧 -> 比对
    task run_one(input integer tag, input integer ty_in);
        begin
            prime;
            n = 0;
            build_expect(freq_hz, freq_hz, ty_in);
            @(posedge clk);
            meas_done = 1'b1;  @(posedge clk);
            meas_done = 1'b0;
            w = 0;
            while (n < 46 && w < 200000) begin @(posedge clk); w = w + 1; end
            @(posedge clk);
            dump_and_cmp(tag);
            repeat (300) @(posedge clk);
        end
    endtask

    // S4: 闸门活性 —— 帧开始后把频率改成别的值, F 行应仍显示旧值, TY 应变 3
    task run_gate_test(input integer tag, input integer f_new);
        begin
            prime;
            n = 0;
            build_expect(freq_hz, f_new, wave_type);   // F=旧值, TY 由 f_new 触发的闸门决定
            @(posedge clk);
            meas_done = 1'b1;  @(posedge clk);
            meas_done = 1'b0;
            repeat (200) @(posedge clk);               // 200 拍: 已过 S_WAIT/S_WF, 正处 S_SEND
            $display("           (第 200 拍把 freq_hz 改成 %0d)", f_new);
            freq_hz = f_new[23:0];
            w = 0;
            while (n < 46 && w < 200000) begin @(posedge clk); w = w + 1; end
            @(posedge clk);
            dump_and_cmp(tag);
            repeat (300) @(posedge clk);
            freq_hz = 24'd12345;                       // 还原, 免得影响后续
        end
    endtask

    integer i;

    initial begin
        $display("====== tb_report_mv: 上报帧 46 字节回归 (v3.3 mV) ======");
        rst_n = 0;
        repeat (10) @(posedge clk);
        rst_n = 1;
        repeat (10) @(posedge clk);

        // ---- S0: 首帧暖机行为(显式断言, 不让它被后续"暖机"掩盖) ----
        freq_hz = 24'd1000; vpp = 8'd139; duty_x10 = 16'd500;
        width_us = 20'd500; wave_type = 2'd1; cal_kn = 16'd8000;
        $display("场景0 复位后首帧(期望 V/D/W 全 0: 3 窗中值的历史槽还是 0)");
        do_frame;
        if (n == 46) begin
            $write("        首帧: ");
            for (i = 12; i < 18; i = i + 1) $write("%c", rxbuf[i]);
            $write("  ");
            for (i = 22; i < 36; i = i + 1) $write("%c", (rxbuf[i] >= 32) ? rxbuf[i] : " ");
            $write("\n");
            if (rxbuf[14] == "0" && rxbuf[15] == "0" && rxbuf[16] == "0" && rxbuf[17] == "0" &&
                rxbuf[22] == "0" && rxbuf[31] == "0")
                $display("        [PASS] 首帧 V/D/W 为 0, 与 3 窗中值暖机特性一致");
            else begin
                fail = fail + 1;
                $display("        [FAIL] 首帧不为 0 —— 中值暖机行为与预期不符, 需复核");
            end
        end
        else begin fail = fail + 1; $display("        [FAIL] 首帧长度异常"); end

        // ---- S1: 默认标定, 正弦, 1000Hz ----
        freq_hz = 24'd1000; vpp = 8'd139; duty_x10 = 16'd500;
        width_us = 20'd500; wave_type = 2'd1; cal_kn = 16'd8000;
        run_one(1, 1);

        // ---- S2: KN=1024 -> 原始 LSB 透传模式, V 应等于 139 ----
        cal_kn = 16'd1024;
        run_one(2, 1);

        // ---- S3: 大数冲击 4 位 mV / 3 位整数占空比 / 5 位脉宽 / 方波 ----
        freq_hz = 24'd12345; vpp = 8'd255; duty_x10 = 16'd1234;
        width_us = 20'd12345; wave_type = 2'd0; cal_kn = 16'd8000;
        run_one(3, 0);

        // ---- S4: 闸门活性: 帧中途把频率从 12345 改成 50000 ----
        run_gate_test(4, 50000);

        if (fail == 0) $display(">>>>>> tb_report_mv 全部通过 <<<<<<");
        else           $display(">>>>>> tb_report_mv 有 %0d 项失败 <<<<<<", fail);
        $finish;
    end

endmodule
