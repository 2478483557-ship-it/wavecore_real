//===========================================================================
// 模块名   : tb_cmd_decoder  (L1 作业用测试平台)
// 用途     : 把 uart_tx → 串口线 → uart_rx → cmd_decoder 整条链路跑起来，
//            仿真里"手动发命令帧"，观察命令是否被正确解析。
// 使用     : Vivado → Add Sources → Add or create simulation sources → 加本文件
//            → Flow Navigator → Run Simulation → Run Behavioral Simulation
//            → 看 Tcl Console 里 [TB] 打印
// 作者     : WaveCore 队长 | 日期: 2026-09-22
//===========================================================================
`timescale 1ns / 1ps

module tb_cmd_decoder;

    // ---------------- 时钟与复位 ----------------
    reg clk = 0, rst_n = 0;
    always #10 clk = ~clk;      // 20ns 周期 = 50MHz

    // ---------------- 发送侧(TB 扮演上位机) ----------------
    reg  [7:0] tx_byte = 0;
    reg        tx_start = 0;
    wire       tx_busy;
    wire       line;            // 串口线(单根信号线示意图)

    uart_tx #(.DIV(108)) u_tx (
        .clk(clk), .rst_n(rst_n), .tx_data(tx_byte),
        .tx_start(tx_start), .tx_busy(tx_busy), .txd(line)
    );

    // ---------------- 接收侧(FPGA 真身) ----------------
    wire [7:0] rx_byte;
    wire       rx_done;

    uart_rx #(.DIV(108)) u_rx (
        .clk(clk), .rst_n(rst_n), .rxd(line),
        .rx_data(rx_byte), .rx_done(rx_done)
    );

    // ---------------- 被测: 命令解码器 ----------------
    wire        preset_load;  wire [1:0] preset_val;
    wire        arb_load;     wire [31:0] arb_fcw;
    wire        dual_load;    wire [31:0] dual_fcw;
    wire        wave_req;     wire [1:0] wave_sel;
    wire [1:0]  trig_mode;
    wire        sf_run;
    wire        sweep_en;
    wire [15:0] cal_kn;         // [0x8C] 电压标定: 每 LSB 多少 mV x1024
    wire        cal_load;

    cmd_decoder dut (
        .clk(clk), .rst_n(rst_n),
        .rx_byte(rx_byte), .rx_done(rx_done),
        .preset_load(preset_load), .preset_val(preset_val),
        .arb_load(arb_load), .arb_fcw(arb_fcw),
        .dual_load(dual_load), .dual_fcw(dual_fcw),
        .wave_req(wave_req), .wave_sel(wave_sel),
        .trig_mode(trig_mode),
        .sf_run(sf_run), .sweep_en(sweep_en),
        .cal_kn(cal_kn), .cal_load(cal_load)
    );

    // ---------------- 观察(等效 ILA 的打印版) ----------------
    integer arb_cnt = 0, sf_cnt = 0, cal_cnt = 0;
    reg sw_prev = 0;                      // sweep_en 上升沿检测(电平只打一次)
    always @(posedge clk) begin
        sw_prev <= sweep_en;
        if (arb_load) begin
            arb_cnt = arb_cnt + 1;
            $display("[TB] arb_load! fcw=%0d (0x%h) 期望 85899(0x14F8B)  [%0t ns]", arb_fcw, arb_fcw, $time);
        end
        if (sf_run) begin
            sf_cnt = sf_cnt + 1;
            $display("[TB] sf_run 脉冲!（自研FFT 将被触发） [%0t ns]", $time);
        end
        if (preset_load) $display("[TB] preset_load! 档位=%0d [%0t ns]", preset_val, $time);
        if (wave_req)    $display("[TB] wave_req 脉冲!(请求波形) [%0t ns]", $time);
        if (sweep_en && !sw_prev) $display("[TB] sweep_en 上升沿 = 1 (扫频开始) [%0t ns]", $time);
        if (cal_load) begin
            cal_cnt = cal_cnt + 1;
            $display("[TB] cal_load 脉冲! cal_kn=%0d (0x%h) -> 每 LSB %0d.%04d mV  [%0t ns]",
                     cal_kn, cal_kn, cal_kn >> 10, ((cal_kn & 16'h03FF) * 10000) >> 10, $time);
        end
    end

    // ---------------- 自动量波形: 低电平宽度(拍数) ----------------
    // 原理: 每个时钟沿取样"上一拍"的 line, 连续低电平的拍数累加;
    //       检测到 低->高 跳变时, 累加值 = 该段低电平持续的时钟数, 宽度 = 拍数 x 20ns
    // 判据: 所有宽度都应该是 2160ns(108 拍) 的整数倍, 最窄段 = 108 拍
    reg     line_d  = 1'b1;               // 上一拍的 line
    integer low_clk = 0;                  // 本段低电平已持续拍数
    integer npulse  = 0, n1bit = 0;       // 低电平总段数 / 其中 1 位宽(108 拍)的段数
    always @(posedge clk) begin
        line_d <= line;
        if (!line) low_clk = low_clk + 1;        // 低电平持续中, 累加拍数
        else begin
            if (!line_d) begin                   // 低->高: 一段低电平结束
                npulse = npulse + 1;
                if (low_clk == 108) n1bit = n1bit + 1;
                if (npulse <= 30)                // 只打前 30 段, 避免刷屏
                    $display("[PULSE] 低电平宽度 = %0d ns ( %0d 拍 )", low_clk * 20, low_clk);
            end
            low_clk = 0;
        end
    end

    // ---------------- 发送任务 ----------------
    task send_byte(input [7:0] b);
        begin
            @(posedge clk);              // 等一拍, 避免与上一次握手竞争
            wait (!tx_busy);
            tx_byte  <= b;
            tx_start <= 1'b1;
            @(posedge clk);
            tx_start <= 1'b0;
            wait (tx_busy);              // 等它真的开始
            wait (!tx_busy);             // 等它发完
        end
    endtask

    // 发一个完整帧: 5A A5 TYPE LEN_H LEN_L PAYLOAD... SUM
    task send_preset1k_frame;
        begin
            send_byte(8'h5A); send_byte(8'hA5);
            send_byte(8'h85); send_byte(8'h00); send_byte(8'h04);
            send_byte(8'hE8); send_byte(8'h03); send_byte(8'h00); send_byte(8'h00);
            send_byte(8'h74);            // SUM
        end
    endtask

    task send_8A_frame;
        begin
            send_byte(8'h5A); send_byte(8'hA5);
            send_byte(8'h8A); send_byte(8'h00); send_byte(8'h01);
            send_byte(8'h00);            // payload
            send_byte(8'h8B);            // SUM
        end
    endtask

    task send_8B_frame(input [7:0] val);   // 扫频开/停
        reg [7:0] s;
        begin
            s = 8'h8B + 8'h00 + 8'h01 + val;
            send_byte(8'h5A); send_byte(8'hA5);
            send_byte(8'h8B); send_byte(8'h00); send_byte(8'h01);
            send_byte(val);
            send_byte(s);               // SUM
        end
    endtask

    // 0x8C 电压标定: payload = knL knH (保留) (保留), LEN=4, 小端 16 位
    task send_8C_frame(input [15:0] kn);
        reg [7:0] s;
        begin
            s = 8'h8C + 8'h00 + 8'h04 + kn[7:0] + kn[15:8];
            send_byte(8'h5A); send_byte(8'hA5);
            send_byte(8'h8C); send_byte(8'h00); send_byte(8'h04);
            send_byte(kn[7:0]); send_byte(kn[15:8]);
            send_byte(8'h00); send_byte(8'h00);
            send_byte(s);               // SUM
        end
    endtask

    // ---------------- 主流程 ----------------
    initial begin
        $display("====== tb_cmd_decoder: 开始 ======");
        rst_n = 0;
        repeat (10) @(posedge clk);
        rst_n = 1;
        repeat (10) @(posedge clk);

        $display(">> 发送 0x85 任意频率帧(1000Hz)...");
        send_preset1k_frame();
        repeat (50) @(posedge clk);

        $display(">> 发送 0x8A 自研FFT 帧...");
        send_8A_frame();
        repeat (50) @(posedge clk);

        $display(">> 发送 0x8B 扫频开始帧...");
        send_8B_frame(8'h01);
        repeat (50) @(posedge clk);

        // ---- 0x8C 电压标定(2026-09-30 补) ----
        // 上电默认 cal_kn=8000; 先发 1024 切"原始 LSB 显示"模式, 再发回 8000。
        $display(">> 发送 0x8C 电压标定帧: KN=1024 (原始 LSB 显示模式)...");
        send_8C_frame(16'd1024);
        repeat (50) @(posedge clk);

        $display(">> 发送 0x8C 电压标定帧: KN=8000 (7.8125mV/LSB 默认标定)...");
        send_8C_frame(16'd8000);
        repeat (50) @(posedge clk);

        $display("====== 统计: arb_load=%0d 次, sf_run=%0d 次, cal_load=%0d 次 ======",
                 arb_cnt, sf_cnt, cal_cnt);
        $display("====== 低电平宽度: 共 %0d 段, 其中 1 位宽 2160ns/108 拍 %0d 段 ======", npulse, n1bit);
        if (arb_cnt == 1 && sf_cnt == 1 && cal_cnt == 2 && cal_kn == 16'd8000)
            $display(">>>>>> 自检通过: 关键命令都解析成功, 0x8C 标定值按预期落地 <<<<<<");
        else
            $display(">>>>>> 自检异常: 请检查波形 (cal_kn 现为 %0d) <<<<<<", cal_kn);
        $display("====== tb_cmd_decoder: 结束 ======");
        $finish;
    end

endmodule
