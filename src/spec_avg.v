//===========================================================================
// 模块名   : spec_avg  (幅度谱 N 帧平均, 0x98 配套)
// 功能     : 对 512 点幅度谱做 N 帧滑动平均, 把底噪压低约 sqrt(N)
//            线性域平均 —— **必须在压缩之前做**。
//            若对 8 位对数码取平均, 得到的是"平均对数幅度", 物理意义错,
//            底噪也降不下来。
// 原理     : 每个 bin 存一个累加值 acc。每来一帧:
//              acc_new = acc_old - acc_old/N + x      (N = 2^SH, 移位精确无误差)
//            稳态时 acc = N*mean, 输出 acc >> SH 即平均幅度。
//            减去 acc_old/N 才叫"滑动"；不减会无限累积、对信号变化不响应。
// 存储     : 512 x 24 位，简单双口（一读一写）-> 1 块 BRAM
// 流水线   : 三级，全部按"同一个 bin 对齐"
//              S1: 发起读 amem[addr]，同时把 addr/mag/we 打一拍
//              S2: q 有效，用 q 与**同拍**的 mag_1 算 nsum，再把 nsum 打一拍
//              S3: 用 nsum_r 写回 addr_2，并作为输出
//            （这里踩过坑：把 S2 的 nsum 直接拿去写 S1 的地址，会把 A 的旧累加
//              加到 B 的新样本上 —— 现象是收敛值不对、且误差随数据不同而变。）
// 作者     : WaveCore 队长 | 日期: 2026-10-18 | v1.1
//===========================================================================
module spec_avg #(
    parameter integer SH = 3          // 平均帧数 = 2^SH（3 -> 8 帧）
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,            // 1=启用平均, 0=直通
    input  wire        we,            // 写入一个幅度点
    input  wire [8:0]  addr,          // bin 0..511
    input  wire [16:0] mag,           // 17 位线性幅度(L1 模)
    output reg  [16:0] mag_out        // 输出（en=0 时等于 mag，延迟 3 拍）
);

    // 单帧幅度 <= 131071(17 位)，32 帧求和 <= 4.2e6 < 2^23，24 位足够
    (* ram_style = "block" *) reg [23:0] amem [0:511];

    // BRAM 上电内容为 X。若直接拿 q 去算，第一个结果就是 X 且会一直传播
    // （仿真里输出恒为 x；上板则是固化的随机值，更难查）。
    // 这段 for 循环 Vivado 会写成 BRAM 的初始化值(INIT_xx)，不占逻辑资源。
    integer ii;
    initial for (ii = 0; ii < 512; ii = ii + 1) amem[ii] = 24'd0;

    //---- 流水线寄存器 ----
    reg [23:0] q;                     // S2: amem[addr] 的旧累加

    // [10-21 补] 读口去掉异步复位后，q 在上电瞬间是 X。
    //   若不初始化，第一拍的 nsum = q - (q>>SH) + mag_1 就是 X，
    //   nsum_r 打一拍后若恰好 we_2 有效，X 就被写回 amem ——
    //   之后整个平均器永久带 X，找峰比较全部失效，自研 FFT 卡死不再上报。
    //   这与 fft_demo 的 m_q 不同：那里 m_q 只喂给组合乘法，X 不影响状态机。
    //   initial 对综合有效（写成 FF 的 INIT 属性），且 q 是普通寄存器，
    //   不参与块 RAM 推断，不会把存储器打回触发器。
    initial q = 24'd0;
    reg        we_1, we_2;
    reg [8:0]  addr_1, addr_2;
    reg [16:0] mag_1;
    reg        en_1;
    reg [23:0] nsum_r;                // S2 算出的新累加，S3 写回

    // q 与 mag_1 属于**同一个 bin**（都对应 S1 那一拍传入的 addr）
    wire [23:0] dec  = q >> SH;
    wire [23:0] nsum = q - dec + {7'd0, mag_1};

    // [10-21 修复] 读口必须**单独**放在一个不带异步复位的 always 里。
    //
    //   原来 q <= amem[addr] 写在带 negedge rst_n 的块里，Vivado 推断 BRAM 时
    //   要求读数据寄存器不能有异步复位（BRAM 输出寄存器不支持），于是直接放弃
    //   BRAM，把 512x24 铺成 12288 个 FDRE。层次报告实测：
    //       u_savg  LUT 3655 / FF 12597 / RAMB 0
    //   这一项独占全设计 LUT 的 33%、FF 的 65%，把整片资源从 35% 推到 53%。
    //
    //   之前没暴露，是因为 avg_en 悬空成 0，整个平均器被综合器当死逻辑裁掉了。
    //   把 0x98 接通后它才真的存在，代价也就露出来了。
    //
    //   修法与 fft_demo 的 f_ram 同理：**读写分开写，读口去复位**。
    always @(posedge clk) begin
        q <= amem[addr];                 // 读口：无复位
    end

    // [10-21 二次修复] 写口也必须独立成一块、且**不带异步复位**。
    //
    //   第一次只把读口拆出来时，综合日志仍报：
    //       "RAM is sensitive to asynchronous reset signal. this RTL style
    //        is not supported." -> RAM "amem_reg" dissolved into registers
    //   因为 amem[addr_2] <= nsum_r 还留在带 negedge rst_n 的块里。
    //
    //   fft_demo 的 f_ram 能进 BRAM，正是读写两个 always 都没有复位。
    always @(posedge clk) begin
        if (we_2) amem[addr_2] <= nsum_r;  // 写口：无复位
    end

    // 其余流水线寄存器照常带复位
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            we_1 <= 1'b0; we_2 <= 1'b0;
            addr_1 <= 9'd0; addr_2 <= 9'd0; mag_1 <= 17'd0; en_1 <= 1'b0;
            nsum_r <= 24'd0;
        end
        else begin
            //---- S1 -> S2 ----
            we_1   <= we;
            addr_1 <= addr;
            mag_1  <= mag;
            en_1   <= en;

            //---- S2: 算新累加，打一拍交给 S3 ----
            nsum_r <= nsum;
            we_2   <= we_1;
            addr_2 <= addr_1;
        end
    end

    //---- 输出级：平均 / 直通，两条路径都延迟 3 拍 ----
    reg [16:0] mo_r;
    reg [16:0] d0, d1, d2;
    reg        en_2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mo_r <= 17'd0; d0 <= 17'd0; d1 <= 17'd0; d2 <= 17'd0;
            en_2 <= 1'b0; mag_out <= 17'd0;
        end
        else begin
            mo_r <= nsum_r >> SH;      // 平均幅度
            d0   <= mag;
            d1   <= d0;
            d2   <= d1;
            en_2 <= en_1;
            mag_out <= en_2 ? mo_r : d2;
        end
    end

endmodule
