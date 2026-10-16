//===========================================================================
// 模块名   : self_fft_1024  (自研 1024 点 Radix-2 DIF FFT, F4 对比用)
// 算法     : 原地 DIF, 输入自然序, 输出位反转; 每级 >>1 (总增益 1/1024)
// 调度     : 与 hw_analysis 金标准逐拍一致 (已验证: 1kHz → bin20)
// 存储     : blk_mem_gen_1 (1024 x 32 单口, 无输出寄存器, 读延迟1拍)
// 运行     : 自动循环: 采1024点(50kHz) -> 10级蝶形 -> 找峰 -> 输出一次
// [09-30 v1.2] 峰频率**抛物线插值**: SF/S2/S3 从 bin 量化(±24Hz)细化到 ±2Hz 级。
//   数值模型: hw_analysis/probe_interp.py(与 RTL 同口径: 偏移二进制/Q15 Hann/L1 模)
//   1kHz: 977 -> 999 ; 方波: 977/2979/4980 -> 999/2998/4998(真值 1000/3000/5000)
//   整数 bin 时 δ=0 -> 与插值前**逐字不变**(USE_INTERP=1'b0 即为插值前的行为)
// 作者     : WaveCore 队长 | 2026-09-16 | v1.2
//===========================================================================
module self_fft_1024 #(
    parameter DECIM    = 32'd1000,
    parameter USE_HANN = 1'b1,    // [09-30] 1=加 Hann 窗(根因修复, 默认) / 0=退回矩形窗(09-30 之前的行为)
    parameter USE_INTERP = 1'b1   // [09-30 v1.2] 1=峰频率抛物线插值 / 0=纯 bin 量化(负向对照)
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  ad_cap,
    input  wire        run,          // 0x8A: 运行一次(脉冲); 平时静默
    input  wire [31:0] decim_cfg,    // [0x8D] 时基抽取比(0 = 用参数 DECIM)
    input  wire [31:0] fs_cfg,       // [0x8D] 等效采样率 Hz(0 = 用 50000)
    input  wire [1:0]  win_cfg,      // [0x90] 窗函数: 0=矩形 1=Hann 2=Blackman  (10-16 新增)
    output reg  [23:0] res_freq,     // 峰值频率(Hz) = bin*50000/1024
    output reg  [23:0] res_f2,       // [调试] 第二峰
    output reg  [23:0] res_f3,       // [调试] 第三峰
    output reg         res_done,     // 一次完成脉冲
    output wire        spec_we,      // [0x8E] 幅度谱写使能(扫描第0趟, bin0..511)
    output wire [8:0]  spec_waddr,   // [0x8E] 写地址 = bin 号
    output wire [7:0]  spec_wdata,   // [0x8E] 压缩幅度(spec_compress 输出)
    output wire        busy,         // [0x8E] 运行中(采集/蝶形/扫描), 供 spec_frame 等待
    output wire [3:0]  dbg_st,       // [调试] 当前状态(0~13)
    output wire [3:0]  dbg2          // [调试] {cap_on, wr_idx[9:7]}
);
    // [09-27 修复] 原此处有一句重复的 "assign dbg_st = st;" 位于 reg 声明之前,
    // 会把 st 隐式声明成 1 位 wire(Vivado 综合放过, 但 XSim 直接报
    // VRFC 10-3380 "identifier 'st' is used before its declaration")。已删, 只保留下方声明后的那一句。
    //======== [0x8D] 时基: 外部配置优先, 未接(0)时回退到参数(保证默认/tb 行为不变) ========
    wire [31:0] decim_use = (decim_cfg == 32'd0) ? DECIM    : decim_cfg;
    wire [31:0] fs_use    = (fs_cfg    == 32'd0) ? 32'd50000 : fs_cfg;

    //======== 存储(单口) ========
    reg  [9:0]  addr;
    reg  [31:0] din;
    reg         we;
    wire [31:0] dout;
    blk_mem_gen_1 u_mem (
        .clka (clk), .addra(addr), .dina(din), .wea(we), .douta(dout)
    );

    //======== 旋转因子 ROM ========
    reg  [9:0]  tw_addr;
    wire [15:0] tw_c, tw_s;
    twiddle_rom u_tw (.clk(clk), .addr(tw_addr), .cos_o(tw_c), .sin_o(tw_s));

    //======== [09-30 新增] Hann 窗(Q15, 1024 点) —— "假峰"的根因修复 ========
    // 回顾: 本通路原先只有**矩形窗**, 1kHz(落在非整数 bin 20.480)时矩形窗的
    //   Dirichlet 核在 bin24 处泄漏 13.6%, 越过"主峰/8 = 12.5%"门限 -> 报出假峰
    //   S2=0001171Hz(2026-09-30 上板实测)。当天先用最小改动 GAP 4->6 压住了症状;
    //   这里做**根因修复**: 加 Hann 窗, 泄漏由 13.6%(最坏相位 14.7%)压到 **0.9%**,
    //   与 IP 通路同一口径。
    //   数值证据: hw_analysis/verify_hann_window.py —— 纯 Python 手写迭代 FFT, 复刻本模块的
    //   窗表/整数标度/L1 模/扫峰门限。它**先逐字复现了板上实测的 S2=0001171Hz(bin24)**,
    //   再由它给出"加 Hann 后 0/24 相位报错、方波 976/2978/4980 一根没少"的结论。
    //
    // 复用: 直接例化 fft_demo 通路已在用的同一个 hann_rom 模块 + 同一份 hann_1024.hex,
    //       **不新增任何文件、不改 Vivado 工程**(hann_rom.v 早已在工程源文件表里)。
    //
    // 标度(关键, 别改错): w 是 Q15, 峰值 32768 = 1.0 -> 窗本身**不改变幅度标度**。
    //   原来  din[31:16] = s << 8                              (s = ad_cap ^ 0x80, 中点归零补码)
    //   现在  din[31:16] = s * w / 32768 * 256 = (s * w) >> 7
    //   满量程仍然是 ±32768 -> 蝶形里"每级 >>>1"的防溢出逻辑**一个字都不用动**。
    //   (s*w)>>7 的范围: s∈[-128,127], w∈[0,32768] -> [-32768, 32512], 正好 16 位有符号。
    //   验证: s=-128, w=32768 -> -4194304 -> [22:7] = 0x8000 = -32768   (OK)
    //         s=+127, w=32768 -> +4161536 -> [22:7] = 0x7F00 = +32512   (OK)
    //
    // 时序(关键, 别改错): w_addr 在采集期间**每拍都跟着 wr_idx**, 而 wr_idx 在两次
    //   采样之间稳定 998 拍。所以 ROM 的 1 拍读延迟, 正好在采样节拍(dcnt==DECIM-1)
    //   当拍把 wmem[wr_idx] 送到 win_w -> 与当拍的 ad_cap 严格对齐。
    //
    // 一键回退: 把 USE_HANN 改成 1'b0 重新综合 -> 整数块被 generate 掉,
    //   行为与 2026-09-30 之前**逐位相同**(已上板验证过的那版)。
    reg  [9:0]  w_addr;
    wire [15:0] win_hann, win_black;
    generate
        if (USE_HANN) begin : g_win
            hann_rom     u_hann_self  (.clk(clk), .addr(w_addr), .wout(win_hann));
            blackman_rom u_black_self (.clk(clk), .addr(w_addr), .wout(win_black));
        end else begin : g_no_win
            assign win_hann  = 16'd0;
            assign win_black = 16'd0;
        end
    endgenerate

    //======== [10-16] 窗函数运行时可切换 (命令 0x90) ========
    // 0=矩形(Q15 满幅 32768) / 1=Hann(默认) / 2=Blackman
    // 关键: 矩形用 Q15=32768 表示, 于是 (s*32768)>>7 == s<<8,
    //       与旧版 USE_HANN=0 的无窗路径**逐位相同** —— 这条是回归判据(tb 里有断言)。
    // 副瓣衰减: 矩形 -13dB / Hann -31dB / Blackman -58dB
    // 主瓣宽度: 矩形 1x / Hann 2x / Blackman 3x  (分辨率与泄漏的取舍)
    wire [15:0] win_w = (win_cfg == 2'd0) ? 16'd32768 :
                        (win_cfg == 2'd2) ? win_black : win_hann;

    wire signed [7:0]  win_s    = ad_cap ^ 8'h80;                    // 中点归零补码(同 09-28 映射修复)
    wire signed [23:0] win_p    = win_s * $signed({1'b0, win_w});    // 8b x 16b, 24 位有符号
    wire        [15:0] win_o    = win_p[22:7];                       // = (s*w) >> 7
    wire        [15:0] cap_samp = USE_HANN ? win_o : {win_s, 8'd0};  // 非加窗分支 = 原来的 s<<8

    //======== 采集 ========
    reg [31:0] dcnt;
    reg [9:0]  wr_idx;
    reg        cap_on;
    reg        run_l;                 // run 脉冲锁存
    reg        done_latch;            // [调试] 完成锁存(once done, stays)
    reg [16:0] done_hold;             // [调试] DONE 停驻计数(约2ms), 供轨迹采样
    reg w1_go, w2_go;                 // [09-19 修复] 读延迟自适应等待(覆盖1/2拍延迟)
    reg pk_go;                        // [09-19 修复] 找峰同样等一拍(2拍延迟)
    assign dbg2 = {done_latch, cap_on, wr_idx[9:8]};

    //======== FSM ========
    reg [4:0] st;                      // [v1.2] 4->5 位(新增插值三态)
    assign dbg_st = st[3:0];
    localparam S_CAP  = 5'd0,
               S_START= 5'd1,
               S_RD1  = 5'd2,
               S_W1   = 5'd3,
               S_RD2  = 5'd4,
               S_W2   = 5'd5,
               S_MUL  = 5'd6,
               S_MUL2 = 5'd7,
               S_MUL3 = 5'd14,
               S_WR1  = 5'd8,
               S_WR2  = 5'd9,
               S_NEXT = 5'd10,
               S_PEAK = 5'd11,
               S_PKRD = 5'd12,
               S_DONE = 5'd13,
               S_NB   = 5'd15,   // [v1.2] 第 4 趟: 采集三个峰的左右邻 bin
               S_NBRD = 5'd16,
               S_ICALC= 5'd17;   // [v1.2] 插值计算(减法循环除法)

    reg [3:0]  stage;
    reg [9:0]  base, j, half, nblk, blk, i1, i2;

    reg signed [15:0] ar, ai, br, bi;
    reg signed [15:0] cr, ci;

    reg [9:0]  pk_addr;
    reg [16:0] pk_best;
    reg [9:0]  pk_bin;
    reg [16:0] m2,m3;                 // [调试] 第2/3峰幅度
    reg [9:0]  b2,b3;                 // [调试] 第2/3峰bin
    // [调试] 采集体检计数
    reg [10:0]  cnt_wr;               // 写入点数
    reg [23:0]  cnt_cy;               // 采集持续拍数
    reg [10:0]  lat_wr;               // 锁存: 点数
    reg [23:0]  lat_cy;               // 锁存: 拍数

    // 位反转
    function [9:0] rev10(input [9:0] v);
        integer k;
        begin
            for (k=0;k<10;k=k+1) rev10[k] = v[9-k];
        end
    endfunction

    //======== [09-27 修复] 峰值判据: 最小间隔 + 幅度门限 ========
    // 问题: 原实现是"幅度前三大"级联, 同一主瓣的相邻 bin(如 976Hz/1025Hz = bin20/21)
    //       会被当成"第二峰", 对外说成"三峰"有答辩风险。
    // 修复: 三趟扫描 0=全局最大 1=第二峰 2=第三峰, 第 2/3 峰必须与已选峰相隔 >= GAP bin;
    //       再叠加"幅度 >= 主峰/8"门限(与 IP 通路 A 行判据一致), 低于门限报 0 = 无有效峰。
    //
    //======== [09-30 上板修复] GAP 4 -> 6: 本通路未加窗, GAP=4 会漏出假峰 ========
    // 现象: 上板跑 1kHz 正弦(非整数 bin)时读出 S2=0001171Hz, 而仿真永远是 0。
    // 根因: 本通路是**矩形窗**(没加窗; Hann 窗只在 IP 通路 fft_demo.v 里)。
    //   1kHz @ fs=50kHz/N=1024 -> 1000/48.828 = bin 20.480, **非整数**。
    //   矩形窗的 Dirichlet 核在 bin24(离主峰 4 bin)处 = 主峰 x 13.6%,
    //   而幅度门限是主峰/8 = 12.5% -> 13.6% 刚好越线 -> 报成"第二峰"。
    //   最坏相位(小数=0.5)时可达 14.3%(离散数值模型实测最坏 14.7%), 所以假峰是
    //   **结构性、时有时无**的, 不是偶发干扰。(命中率模型实测: 固定 1kHz 扫 24 个相位
    //   -> 24/24 全报; 扫频 800~1200Hz -> 4/41 报。旧稿写的"约 65%"是未实测的粗估。)
    // 为什么仿真抓不到: sim/fft_check 的激励是"1024 点正好 k 个整周期",
    //   谱线精确落在整数 bin, 矩形窗泄漏在该处恰好为 0 -> 假峰永远不出现。
    //   ★ 又一次"仿真通过 != 硬件正确", 激励必须覆盖**非整数 bin** 的情况。
    // 修法: GAP 4 -> 6。第一个合格 bin 移到 bin26, 泄漏降到 8.7%(最坏相位 9.1%),
    //   稳定低于 12.5% 门限。对真实谱峰无影响 —— 1kHz 方波的 3/5 次谐波在 bin61/bin102,
    //   离基波 41/82 bin, 远大于 6; 双音 80bin 同样不受影响。
    // [09-30 下午 更新] "根因修复"已采纳: 本通路也加上了 Hann 窗(见上方 USE_HANN 段),
    //   泄漏由 13.6%(最坏相位 14.7%)降到 **0.9%**, 对 12.5% 门限有 **16 倍余量**。
    //   两条修法的性质完全不同(答辩别答错): GAP=6 是"**不去看它**"(把越线 bin 划进保护带,
    //   泄漏本身一点没减); 加窗才是"**它本来就小**"。
    //   理论上 GAP 可以退回 4, 但**故意保留 6**:
    //   ① 双音两峰相隔 80 bin、方波谐波相隔 41/82 bin, GAP=6 完全不影响真实峰;
    //   ② 少动一处就少一份回归风险, 而 GAP=6 这一版已经在板上验证通过。
    localparam [9:0] GAP = 10'd6;      // [09-30] 原为 10'd4; 矩形窗需 >=6 bin 才压住泄漏
    reg  [1:0] scan;                   // 当前第几趟
    wire [9:0] cur_bin = rev10(pk_addr);
    wire [9:0] d_pk = (cur_bin > pk_bin) ? (cur_bin - pk_bin) : (pk_bin - cur_bin);
    wire [9:0] d_b2 = (cur_bin > b2)     ? (cur_bin - b2)     : (b2 - cur_bin);
    wire       far_pk  = (d_pk >= GAP);
    wire       far_all = (d_pk >= GAP) && (d_b2 >= GAP);

    //======== [09-30 v1.2] 峰频率抛物线插值 ========
    // 谱峰是主瓣不是尖峰: 用峰值 bin 与左右邻 bin 的 L1 模做抛物线插值,
    //   δ = 0.5*(c-a)/(2b-a-c)   f = (k+δ)*fs/N
    // 取邻居的办法: 加"第 4 趟扫描", 依次访问 0..1023, 把三个峰各自的 (左,中,右)
    //   bin 幅度收进寄存器 —— 与找峰同一套读时序, 不新增存储访问、不动蝶形。
    // δ 的 Q8 定标 = ±128(±0.5 bin); 除法用**减法循环**(商 <=128, 最多 128 拍),
    //   不用综合器的组合除法器(那会拉出长组合链)。
    // 边界: 峰 bin<=1 或 邻 bin 缺失 -> δ=0(退回整数 bin 公式, 与旧行为一致);
    //   2/3 峰不满足"幅度>=主峰/8"门限 -> 报 0(与旧行为一致)。
    reg  [9:0] nb_addr;
    reg        nb_go;
    wire [9:0] nb_bin = rev10(nb_addr);
    reg [16:0] n_a0,n_b0,n_c0, n_a1,n_b1,n_c1, n_a2,n_b2,n_c2;
    reg [16:0] ic_a, ic_b, ic_c;
    reg [9:0]  ic_bin;
    reg        ic_val, ic_ok;
    reg [1:0]  ic_ph, ip_pk;
    reg [24:0] ic_rem;
    reg [7:0]  ic_q;
    reg signed [18:0] ic_ns;                                   // c-a
    wire signed [20:0] ic_dps = ($signed({3'b0, ic_b}) <<< 1) - $signed({3'b0, ic_a}) - $signed({3'b0, ic_c});
    wire               ic_dpok = ic_dps > 21'sd16;             // 分母太小 -> 不插值
    wire [20:0]        ic_dpu  = ic_dps[20:0];                 // 已知 >16, 当无符号用
    wire signed [18:0] ic_nsw = $signed({2'b0, ic_c}) - $signed({2'b0, ic_a});
    wire [17:0]        ic_abs = ic_nsw[18] ? (~ic_nsw[17:0] + 18'd1) : ic_nsw[17:0];
    wire signed [9:0]  ic_dq  = ic_ns[18] ? -$signed({2'b00, ic_q}) : $signed({2'b00, ic_q});
    wire [17:0]        ic_bin8 = {ic_bin, 8'd0};
    wire signed [19:0] ic_x   = $signed({2'b0, ic_bin8}) + ic_dq;
    wire signed [31:0] fs_s   = fs_use;                       // 正数(fs<=100kHz, 最高位恒 0)
    wire signed [51:0] ic_fp  = $signed(ic_x) * fs_s;         // 20b x 32b
    wire signed [39:0] ic_f   = ic_fp >>> 18;                 // = (bin+δ) * fs / N

    // ---- 蝶形组合运算 ----
    wire signed [16:0] sumr = ar + br;        // 17位
    wire signed [16:0] sumi = ai + bi;
    wire signed [16:0] difr = ar - br;
    wire signed [16:0] difi = ai - bi;
    wire signed [15:0] o1r = sumr >>> 1;      // 除2(防溢出)
    wire signed [15:0] o1i = sumi >>> 1;
    // [09-17 时序修复] 乘法先打拍(消除 mult->sub->shift 长链)
    reg  signed [31:0] p_rr, p_ii, p_ri, p_ir;
    wire signed [15:0] o2r = (p_rr - p_ii) >>> 16; // 打拍后仅剩 sub+shift(短)
    wire signed [15:0] o2i = (p_ri + p_ir) >>> 16;

    // ---- 峰值功率(有符号平方, 33位) ----
    // [09-17 时序修复] 找峰用 L1 范数(|re|+|im|): 免乘法, 单调性足够找峰
    wire signed [15:0] d_re = dout[31:16];
    wire signed [15:0] d_im = dout[15:0];
    wire [16:0] d_mag = (d_re[15] ? (~d_re + 1) : d_re) + (d_im[15] ? (~d_im + 1) : d_im);

    //======== [09-30 新增] 0x8E 幅度谱: 扫描第 0 趟顺手导出压缩幅度 ========
    // 时机: 三趟找峰扫描的**第 0 趟会逐个访问全部 1024 个地址**, 且处理周期
    //   恰好拿到该 bin 的 L1 模 d_mag(与找峰同一口径, 不新增任何存储访问)。
    // 只导出正半轴 bin 0..511(实数 FFT 共轭对称, 上半轴冗余; 与 0x8E 帧 512 点吻合)。
    // 压缩: spec_compress(前导零+移位, ~70 LUT)。两级打拍避开长组合链:
    //   第 X 拍: d_mag/cur_bin 有效 -> 记入 sc_m1/sc_b1
    //   第 X+1 拍: 组合压缩 sc_y -> 记入 sc_y2/sc_b2
    //   第 X+2 拍: spec_we=1, spec_buf 在时钟沿写入 => 扫描循环不用插等待
    // ★ 若删掉这段, 0x8E 帧会全 0(但其它功能一行不受影响)
    reg  [16:0] sc_m1;
    reg  [9:0]  sc_b1;
    reg         sc_w1;
    reg  [7:0]  sc_y2;
    reg  [8:0]  sc_b2;
    reg         sc_w2;
    wire [7:0]  sc_y;
    spec_compress u_scomp (.mag(sc_m1), .y(sc_y));
    wire sc_valid = (st == S_PKRD) && pk_go && (scan == 2'd0);   // 第0趟的处理周期
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sc_m1<=17'd0; sc_b1<=10'd0; sc_w1<=1'b0;
            sc_y2<=8'd0;  sc_b2<=9'd0;  sc_w2<=1'b0;
        end
        else begin
            sc_m1 <= d_mag;
            sc_b1 <= cur_bin;
            sc_w1 <= sc_valid && (cur_bin <= 10'd511);
            sc_y2 <= sc_y;
            sc_b2 <= sc_b1[8:0];
            sc_w2 <= sc_w1;
        end
    end
    assign spec_we    = sc_w2;
    assign spec_waddr = sc_b2;
    assign spec_wdata = sc_y2;
    assign busy       = cap_on || (st != S_CAP);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st<=S_CAP; dcnt<=0; wr_idx<=0; cap_on<=1'b0; run_l<=1'b0; done_latch<=1'b0;
            done_hold<=17'd0; w1_go<=1'b0; w2_go<=1'b0;
            cnt_wr<=11'd0; cnt_cy<=24'd0; lat_wr<=11'd0; lat_cy<=24'd0;
            pk_go<=1'b0;
            addr<=0; din<=0; we<=0; tw_addr<=0; w_addr<=0;
            stage<=0; base<=0; j<=0; half<=10'd512; nblk<=10'd1; blk<=0; i1<=0; i2<=0;
            ar<=0;ai<=0;br<=0;bi<=0;cr<=0;ci<=0;
            p_rr<=0;p_ii<=0;p_ri<=0;p_ir<=0;
            res_freq<=0; res_done<=0; pk_addr<=0; pk_best<=0; pk_bin<=0; scan<=2'd0;
            nb_addr<=10'd0; nb_go<=1'b0; ip_pk<=2'd0; ic_ph<=2'd0;
            n_a0<=0;n_b0<=0;n_c0<=0; n_a1<=0;n_b1<=0;n_c1<=0; n_a2<=0;n_b2<=0;n_c2<=0;
            ic_a<=0;ic_b<=0;ic_c<=0; ic_bin<=10'd0; ic_val<=1'b0; ic_ok<=1'b0;
            ic_rem<=25'd0; ic_q<=8'd0; ic_ns<=19'd0;
        end
        else begin
            we <= 1'b0;
            res_done <= 1'b0;
            if (run) begin run_l <= 1'b1; done_latch <= 1'b0; end  // 新任务清锁存

            // ---- 采集(仅收到 run 后进行一次) ----
            if (!cap_on && run_l && st==S_CAP) begin
                cap_on <= 1'b1;
                run_l  <= 1'b0;
                dcnt   <= 32'd0;
                wr_idx <= 10'd0;
                cnt_wr <= 11'd0;      // [调试] 清体检计数
                cnt_cy <= 24'd0;
            end
            else if (cap_on && st==S_CAP) begin
                cnt_cy <= cnt_cy + 24'd1;   // [调试] 采集拍数
                // [09-30] 窗系数地址: 采集期间每拍都跟住 wr_idx。
                //   wr_idx 只在采样节拍才 +1, 两次采样之间稳定 998 拍,
                //   所以 ROM 的 1 拍读延迟恰好让 win_w 在采样节拍当拍 = wmem[wr_idx]。
                w_addr <= wr_idx;
                    if (dcnt==decim_use-32'd1) begin
                        dcnt <= 0;
                        addr <= wr_idx; we <= 1'b1;
                        // [09-28 修复·重要] ADC 是"偏移二进制"(中点 128), 而蝶形与找峰
                        // 全程按"有符号补码"解释 dout[31:16]。原来的 {ad_cap,24'd0} 相当于
                        // 把 ad_cap 当"有符号 8 位"用: ad_cap>=128 会变成负数,
                        // 于是在 128 处出现一个"断崖", 正弦(29~227)被劈成锯齿,
                        // 凭空造出 3 次/5 次谐波 -> S2/S3 全是假的;
                        // 而且 ad_cap=128 会映到 -32768(满量程负), 直流分量巨大。
                        // 修法: 异或 0x80 = 减 128(mod 256), 得到真正的中点归零补码。
                        //   128 -> 0x00 ->    0      (中点归零)
                        //   228 -> 0x64 -> +25600    (原 228-128=+100)
                        //    28 -> 0x9C -> -25600    (原  28-128=-100)
                        // 对照: IP 通路 fft_demo.v 一直是 $signed({8'd0,m_q})-128, 本来就是对的。
                        // [09-30] din 的上 16 位由 cap_samp 给出:
                        //   加窗时 = (s*w)>>7 ; 不加窗时 = s<<8 (与 09-30 之前逐位相同)
                        din  <= {cap_samp, 16'd0};
                        cnt_wr <= cnt_wr + 11'd1;    // [调试] 点数
                    if (wr_idx==10'd1023) begin
                        wr_idx<=0; cap_on<=1'b0; st<=S_START;
                        lat_wr <= cnt_wr + 11'd1;   // [调试] 锁存(含本拍)
                        lat_cy <= cnt_cy + 24'd1;
                    end
                    else wr_idx <= wr_idx + 10'd1;
                end
                else dcnt <= dcnt + 32'd1;
            end

            case (st)
                S_CAP: ;    // [09-19 修复] 空项: 防 default 吞掉"采集结束->S_START"的赋值
                S_START: begin
                    stage<=0; base<=0; blk<=0; j<=0;
                    half<=10'd512; nblk<=10'd1;
                    st<=S_RD1;
                end
                S_RD1: begin i1<=base+j; addr<=base+j; w1_go<=1'b0; st<=S_W1; end
                S_W1:  begin
                             if (!w1_go) w1_go<=1'b1;          // 多等一拍: 兼容 2 拍读延迟
                             else begin
                                 ar<=dout[31:16]; ai<=dout[15:0];
                                 i2<=(base+j)+half; st<=S_RD2;
                             end
                         end
                S_RD2: begin addr<=i2; w2_go<=1'b0; st<=S_W2; end
                S_W2:  begin
                             if (!w2_go) w2_go<=1'b1;          // 多等一拍
                             else begin
                                 br<=dout[31:16]; bi<=dout[15:0];
                                 tw_addr<=j<<stage[3:0]; st<=S_MUL;
                             end
                         end
                S_MUL: begin st<=S_MUL2; end
                S_MUL2:begin cr<=tw_c; ci<=tw_s; st<=S_MUL3; end
                S_MUL3:begin                                  // 乘法打拍
                             p_rr <= difr * cr;
                             p_ii <= difi * ci;
                             p_ri <= difr * ci;
                             p_ir <= difi * cr;
                             st   <= S_WR1;
                         end
                S_WR1: begin addr<=i1; din<={o1r,o1i}; we<=1'b1; st<=S_WR2; end
                S_WR2: begin addr<=i2; din<={o2r,o2i}; we<=1'b1; st<=S_NEXT; end
                S_NEXT: begin
                    if (j+1 < half) begin
                        j  <= j + 10'd1;
                        st <= S_RD1;                    // 修: 推进后回读下一只蝴蝶
                    end
                    else begin
                        j <= 0;
                        if (blk+1 < nblk) begin
                            blk  <= blk + 10'd1;
                            base <= base + (half<<1);
                            st   <= S_RD1;              // 修: 换块后回读
                        end
                        else begin
                            blk <= 0; base <= 0;
                            if (stage==4'd9) begin
                                pk_addr<=0; pk_best<=0; pk_bin<=0; m2<=0; m3<=0; b2<=0; b3<=0;
                                scan<=2'd0;
                                st<=S_PEAK;
                            end
                            else begin
                                stage<=stage+4'd1;
                                half<=half>>1;
                                nblk<=nblk<<1;
                                st<=S_RD1;
                            end
                        end
                    end
                end
                S_PEAK: begin addr<=pk_addr; pk_go<=1'b0; st<=S_PKRD; end
                S_PKRD: begin
                 if (!pk_go) pk_go<=1'b1;                  // 等一拍(2拍读延迟)
                 else begin
                    // [09-27] 三趟扫描: 0=全局最大, 1=第二峰(离主峰>=GAP), 2=第三峰(离前两峰>=GAP)
                    // [09-28] 排除 bin0(直流): 直流不是"频率分量"。修复输入映射后直流≈0,
                    //        这一条只是兜底, 防止残余直流把 SF 顶成 0Hz。
                    if (cur_bin >= 10'd1 && cur_bin <= 10'd511) begin   // 只看正半轴, 跳过直流
                        case (scan)
                            2'd0: if (d_mag > pk_best) begin
                                      pk_best <= d_mag; pk_bin <= cur_bin;
                                  end
                            2'd1: if (far_pk && (d_mag > m2)) begin
                                      m2 <= d_mag; b2 <= cur_bin;
                                  end
                            default: if (far_all && (d_mag > m3)) begin
                                      m3 <= d_mag; b3 <= cur_bin;
                                  end
                        endcase
                    end
                    if (pk_addr==10'd1023) begin
                        if (scan != 2'd2) begin                // 还有下一趟: 重头再扫
                            scan    <= scan + 2'd1;
                            pk_addr <= 10'd0;
                            st      <= S_PEAK;
                        end
                        else if (USE_INTERP) begin            // [v1.2] 第 4 趟: 收邻居
                            nb_addr <= 10'd0; nb_go <= 1'b0;
                            ip_pk   <= 2'd0;  ic_ph <= 2'd0;
                            n_a0<=0; n_b0<=0; n_c0<=0;
                            n_a1<=0; n_b1<=0; n_c1<=0;
                            n_a2<=0; n_b2<=0; n_c2<=0;
                            st      <= S_NB;
                        end
                        else st<=S_DONE;
                    end
                    else begin pk_addr<=pk_addr+10'd1; st<=S_PEAK; end
                 end
                end
                // ---- [v1.2] 第 4 趟: 逐 bin 比对, 收集三个峰的邻 bin 幅度 ----
                S_NB: begin addr<=nb_addr; nb_go<=1'b0; st<=S_NBRD; end
                S_NBRD: begin
                    if (!nb_go) nb_go<=1'b1;                 // 与找峰同一套 2 拍读等待
                    else begin
                        if (nb_bin == pk_bin - 10'd1)  n_a0 <= d_mag;
                        if (nb_bin == pk_bin)          n_b0 <= d_mag;
                        if (nb_bin == pk_bin + 10'd1)  n_c0 <= d_mag;
                        if (nb_bin == b2 - 10'd1)      n_a1 <= d_mag;
                        if (nb_bin == b2)              n_b1 <= d_mag;
                        if (nb_bin == b2 + 10'd1)      n_c1 <= d_mag;
                        if (nb_bin == b3 - 10'd1)      n_a2 <= d_mag;
                        if (nb_bin == b3)              n_b2 <= d_mag;
                        if (nb_bin == b3 + 10'd1)      n_c2 <= d_mag;
                        if (nb_addr==10'd1023) st<=S_ICALC;
                        else begin nb_addr<=nb_addr+10'd1; st<=S_NB; end
                    end
                end
                // ---- [v1.2] 逐峰计算 δ 并写回 res_freq/res_f2/res_f3 ----
                S_ICALC: begin
                    case (ic_ph)
                        2'd0: begin                              // 选峰 + 取 (a,b,c)
                            case (ip_pk)
                                2'd0: begin ic_a<=n_a0; ic_b<=n_b0; ic_c<=n_c0; ic_bin<=pk_bin;
                                            ic_val<=1'b1; end
                                2'd1: begin ic_a<=n_a1; ic_b<=n_b1; ic_c<=n_c1; ic_bin<=b2;
                                            ic_val<=(b2!=10'd0) && (m2 >= (pk_best>>3)); end
                                default: begin ic_a<=n_a2; ic_b<=n_b2; ic_c<=n_c2; ic_bin<=b3;
                                            ic_val<=(b3!=10'd0) && (m3 >= (pk_best>>3)); end
                            endcase
                            ic_ph <= 2'd1;
                        end
                        2'd1: begin                              // 装载除法
                            ic_ns  <= ic_nsw;
                            ic_ok  <= ic_val && (ic_bin >= 10'd2) && ic_dpok;
                            ic_rem <= {7'b0, ic_abs} << 7;
                            ic_q   <= 8'd0;
                            ic_ph  <= 2'd2;
                        end
                        2'd2: begin                              // 减法循环(商 <=128)
                            if (ic_ok && (ic_rem >= {4'b0, ic_dpu}) && (ic_q != 8'd128)) begin
                                ic_rem <= ic_rem - {4'b0, ic_dpu};
                                ic_q   <= ic_q + 8'd1;
                            end
                            else ic_ph <= 2'd3;
                        end
                        default: begin                           // 出结果
                            if (!ic_val) begin                   // 无有效峰 -> 0(同旧行为)
                                case (ip_pk)
                                    2'd1: res_f2   <= 24'd0;
                                    2'd2: res_f3   <= 24'd0;
                                    default: res_freq <= 24'd0;
                                endcase
                            end
                            else if (!ic_ok) begin               // 边界/整形差 -> 整数 bin(同旧行为)
                                case (ip_pk)
                                    2'd1: res_f2   <= (b2*fs_use)>>10;
                                    2'd2: res_f3   <= (b3*fs_use)>>10;
                                    default: res_freq <= (pk_bin*fs_use)>>10;
                                endcase
                            end
                            else begin                            // 插值结果(负数截 0)
                                case (ip_pk)
                                    2'd1: res_f2   <= ic_f[39] ? 24'd0 : ic_f[23:0];
                                    2'd2: res_f3   <= ic_f[39] ? 24'd0 : ic_f[23:0];
                                    default: res_freq <= ic_f[39] ? 24'd0 : ic_f[23:0];
                                endcase
                            end
                            ic_ph <= 2'd0;
                            if (ip_pk == 2'd2) st <= S_DONE;
                            else               ip_pk <= ip_pk + 2'd1;
                        end
                    endcase
                end
                S_DONE: begin
                    // [09-30 v1.2] RES 已在 S_ICALC 写好; 仅当关掉插值时才走这条老路
                    if (!USE_INTERP) begin
                        // [09-30 深夜 BUGFIX] 原来 24'd50000 -> 按 Verilog 位宽规则实际按 24 位相乘,
                        //   pk_bin>=336 (16406Hz) 起静默溢出, 读数恰好偏 -16384Hz。
                        //   改 32 位: 511*50000=25,550,000 << 2^32。
                        //   证据: hw_analysis/check_self_fft_overflow.py（逐 bin 复核）
                        res_freq <= (pk_bin*fs_use)>>10;
                        // [09-27] 门限: 幅度 >= 主峰/8 才认(与 IP 通路 A 行判据一致); 否则报 0 = 无有效峰
                        res_f2   <= (m2 >= (pk_best>>3)) ? ((b2*fs_use)>>10) : 24'd0;
                        res_f3   <= (m3 >= (pk_best>>3)) ? ((b3*fs_use)>>10) : 24'd0;
                    end
                    res_done <= 1'b1;                     // 单拍完成脉冲
                    st<=S_CAP; cap_on<=1'b0; wr_idx<=0; dcnt<=0;   // 回静默, 等下一条 0x8A
                end
                default: st<=S_CAP;
            endcase
        end
    end
endmodule
