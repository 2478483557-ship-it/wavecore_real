# -*- coding: utf-8 -*-
import io
p='sim/fft_check/tb_self_fft.v'
t=io.open(p,encoding='utf-8').read()
anchor = '        $display("=====================================================");'
block = '''        $display("-------- [10-18] 自适应选窗: 频偏小用矩形, 频偏大用 Hann --------");
        begin : auto_t
            integer k2;
            // 场景A: 整数 bin 附近的信号 -> 频偏小 -> 应选矩形(win_auto_pick=0)
            // 场景B: 半个 bin 附近的信号 -> 频偏大 -> 应选 Hann(win_auto_pick=1)
            // 做法: 直接用查表激励, 但把表换成"整 bin"与"半 bin"两种, 跑两次看 pick
            win_auto = 1'b1;
            for (k2 = 0; k2 < 2; k2 = k2 + 1) begin
                sel = (k2 == 0) ? 3'd1 : 3'd4;   // 1=sin20(整bin) 4=sin20p5(半bin)
                @(negedge clk); run = 1'b1; @(negedge clk); run = 1'b0;
                @(posedge res_done); repeat (10) @(posedge clk);
                $display("    场景%0s: |delta| 判定 -> %0s",
                         (k2 == 0) ? "A(整bin~20)" : "B(半bin~20.5)",
                         u_dut.win_auto_pick ? "Hann" : "矩形");
            end
            win_auto = 1'b0;
            repeat (20) @(posedge clk);
        end

'''
if '自适应选窗: 频偏小用矩形' not in t:
    t = t.replace(anchor, block + anchor, 1)
    io.open(p,'w',encoding='utf-8',newline='\n').write(t)
    print('已加自适应窗测试场景')
