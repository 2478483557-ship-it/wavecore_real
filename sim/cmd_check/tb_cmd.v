`timescale 1ns/1ps
// 自动生成: 把真实命令帧喂给 cmd_decoder, 看各 *_set 有没有脉冲
module tb_cmd;
    reg clk = 0, rst_n = 0, rx_done = 0;
    reg [7:0] rx_byte;
    wire  preset_load;
    wire [1:0] preset_val;
    wire  arb_load;
    wire [31:0] arb_fcw;
    wire  dual_load;
    wire [31:0] dual_fcw;
    wire  wave_req;
    wire [1:0] wave_sel;
    wire [1:0] trig_mode;
    wire  sf_run;
    wire  sweep_en;
    wire [15:0] cal_kn;
    wire  cal_load;
    wire  spec_req;
    wire  tb_set;
    wire [1:0] tb_sel;
    wire  pre_set;
    wire [1:0] pre_sel;
    wire  win_set;
    wire [1:0] win_sel;
    wire  ovl_set;
    wire  ovl_sel;
    wire  ifft_set;
    wire [9:0] ifft_lo;
    wire [9:0] ifft_hi;
    wire  play_set;
    wire  play_sel;
    reg ifft_seen = 0, ovl_seen = 0, win_seen = 0, play_seen = 0, arb_seen = 0;
    integer npass = 0, nfail = 0;

    always #10 clk = ~clk;
    always @(posedge clk) begin
        if (ifft_set) ifft_seen <= 1'b1;
        if (ovl_set)  ovl_seen  <= 1'b1;
        if (win_set)  win_seen  <= 1'b1;
        if (play_set) play_seen <= 1'b1;
        if (arb_load) arb_seen  <= 1'b1;
    end

    cmd_decoder u_dut (
        .clk(clk), .rst_n(rst_n), .rx_byte(rx_byte), .rx_done(rx_done),
        .preset_load   (preset_load),
        .preset_val    (preset_val),
        .arb_load      (arb_load),
        .arb_fcw       (arb_fcw),
        .dual_load     (dual_load),
        .dual_fcw      (dual_fcw),
        .wave_req      (wave_req),
        .wave_sel      (wave_sel),
        .trig_mode     (trig_mode),
        .sf_run        (sf_run),
        .sweep_en      (sweep_en),
        .cal_kn        (cal_kn),
        .cal_load      (cal_load),
        .spec_req      (spec_req),
        .tb_set        (tb_set),
        .tb_sel        (tb_sel),
        .pre_set       (pre_set),
        .pre_sel       (pre_sel),
        .win_set       (win_set),
        .win_sel       (win_sel),
        .ovl_set       (ovl_set),
        .ovl_sel       (ovl_sel),
        .ifft_set      (ifft_set),
        .ifft_lo       (ifft_lo),
        .ifft_hi       (ifft_hi),
        .play_set      (play_set),
        .play_sel      (play_sel)
    );

    task snd(input [7:0] b);
        begin
            @(negedge clk); rx_byte = b; rx_done = 1'b1;
            @(negedge clk); rx_done = 1'b0;
            repeat (4) @(negedge clk);
        end
    endtask

    task chk(input [8*46:1] nm, input c);
        begin
            if (c) begin npass = npass + 1; $display("  PASS  %0s", nm); end
            else   begin nfail = nfail + 1; $display("  FAIL  %0s", nm); end
        end
    endtask

    initial begin
        $display("==== cmd_decoder 命令解码回归 ====");
        repeat (5) @(posedge clk); rst_n = 1; repeat (5) @(posedge clk);

        // 对照组: 0x85 设 1000Hz (板上已知可用)
        snd(8'h5A); snd(8'hA5); snd(8'h85); snd(8'h00); snd(8'h04);
        snd(8'hE8); snd(8'h03); snd(8'h00); snd(8'h00); snd(8'h74);
        repeat (6) @(negedge clk);
        $display("  0x85 后 arb_load脉冲=%b", arb_seen);
        chk("0x85 能被解码(对照组)", arb_seen === 1'b1);

        // 被测 1: 0x92 掩膜 100~104
        snd(8'h5A); snd(8'hA5); snd(8'h92); snd(8'h00); snd(8'h04);
        snd(8'h64); snd(8'h00); snd(8'h68); snd(8'h00); snd(8'h62);
        repeat (6) @(negedge clk);
        $display("  0x92 后 ifft_set脉冲=%b lo=%0d hi=%0d", ifft_seen, ifft_lo, ifft_hi);
        chk("0x92 能被解码", ifft_seen === 1'b1);
        chk("掩膜低 bin = 100", ifft_lo == 10'd100);
        chk("掩膜高 bin = 104", ifft_hi == 10'd104);

        // 被测 2: 0x93 回放开
        snd(8'h5A); snd(8'hA5); snd(8'h93); snd(8'h00); snd(8'h01); snd(8'h01); snd(8'h95);
        repeat (6) @(negedge clk);
        $display("  0x93 后 play_set脉冲=%b play_sel=%b", play_seen, play_sel);
        chk("0x93 能被解码且 play_sel=1", (play_seen === 1'b1) && (play_sel === 1'b1));

        $display("--------------------------------------------------");
        $display("RESULT: PASS=%0d FAIL=%0d", npass, nfail);
        $finish;
    end
endmodule
