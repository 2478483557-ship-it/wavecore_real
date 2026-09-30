//===========================================================================
// 模块名 : xfft_0 (行为级"替身", 仅用于 sim/fft_demo_check)
// 用途   : fft_demo 的等价性回归 —— 不需要真的做 FFT, 只要能:
//          1) 收下 s_axis 上灌进来的 4096 个样点, 打一个滚动校验和
//          2) 回灌一条固定谱(第 5 根谱线有幅度), 让找峰/tlast 状态机跑完
//          接口名必须和真 IP 一致(fft_demo 用的是名字连接)
// 作者   : WaveCore 队长 | 日期: 2026-09-30
//===========================================================================

module xfft_0 (
    input  wire        aclk,
    // ---- config ----
    input  wire [7:0]  s_axis_config_tdata,
    input  wire        s_axis_config_tvalid,
    output wire        s_axis_config_tready,
    // ---- data in ----
    input  wire [31:0] s_axis_data_tdata,
    input  wire        s_axis_data_tvalid,
    output wire        s_axis_data_tready,
    input  wire        s_axis_data_tlast,
    // ---- data out ----
    output reg  [31:0] m_axis_data_tdata,
    output reg  [7:0]  m_axis_data_tuser,
    output reg         m_axis_data_tvalid,
    input  wire        m_axis_data_tready,
    output reg         m_axis_data_tlast,
    // ---- status / events ----
    output wire [7:0]  m_axis_status_tdata,
    output wire        m_axis_status_tvalid,
    input  wire        m_axis_status_tready,
    output wire        event_frame_started,
    output wire        event_tlast_unexpected,
    output wire        event_tlast_missing,
    output wire        event_status_channel_halt,
    output wire        event_data_in_channel_halt,
    output wire        event_data_out_channel_halt
);

    localparam integer NFFT = 4096;

    assign s_axis_config_tready = 1'b1;
    assign s_axis_data_tready   = 1'b1;
    assign m_axis_status_tdata  = 8'd0;
    assign m_axis_status_tvalid = 1'b0;
    assign event_frame_started        = 1'b0;
    assign event_tlast_unexpected     = 1'b0;
    assign event_tlast_missing        = 1'b0;
    assign event_status_channel_halt  = 1'b0;
    assign event_data_in_channel_halt = 1'b0;
    assign event_data_out_channel_halt= 1'b0;

    // ---- 样点收集 + 校验和 ----
    integer      capn;
    reg [31:0]   chk_xor;      // 移位异或校验和
    reg [31:0]   chk_sum;      // 算术和
    reg [15:0]   fb0, fb1, fb2, fb3;   // 前 4 个样点, 便于肉眼定位
    integer      nframe;

    // ---- 回灌状态 ----
    reg          emit;
    integer      emit_n;

    initial begin
        capn    = 0;
        chk_xor = 32'd0;
        chk_sum = 32'd0;
        fb0 = 16'hxxxx; fb1 = 16'hxxxx; fb2 = 16'hxxxx; fb3 = 16'hxxxx;
        nframe  = 0;
        emit    = 1'b0;
        emit_n  = 0;
        m_axis_data_tdata  = 32'd0;
        m_axis_data_tuser  = 8'd0;
        m_axis_data_tvalid = 1'b0;
        m_axis_data_tlast  = 1'b0;
    end

    // ---- 收数 ----
    always @(posedge aclk) begin
        if (s_axis_data_tvalid && s_axis_data_tready) begin
            if (capn == 0) fb0 <= s_axis_data_tdata[15:0];
            if (capn == 1) fb1 <= s_axis_data_tdata[15:0];
            if (capn == 2) fb2 <= s_axis_data_tdata[15:0];
            if (capn == 3) fb3 <= s_axis_data_tdata[15:0];
            chk_xor <= {chk_xor[30:0], chk_xor[31] ^ chk_xor[21] ^ chk_xor[1]}
                       ^ {16'd0, s_axis_data_tdata[15:0]};
            chk_sum <= chk_sum + {16'd0, s_axis_data_tdata[15:0]};
            capn    <= capn + 1;
        end
        if (s_axis_data_tlast) begin
            nframe <= nframe + 1;
            $display("[STUB] frame %0d captured: n=%0d chk_xor=%08h chk_sum=%08h  fb=%0d,%0d,%0d,%0d",
                     nframe, capn, chk_xor, chk_sum, fb0, fb1, fb2, fb3);
            emit   <= 1'b1;
            emit_n <= 0;
        end
    end

    // ---- 回灌固定谱: 第 5 根谱线有幅度, 其余为 0 ----
    always @(posedge aclk) begin
        if (emit) begin
            m_axis_data_tvalid <= 1'b1;
            if (emit_n == 5) begin
                m_axis_data_tdata <= {16'd0, 16'd2000};   // im=0, re=2000
            end
            else begin
                m_axis_data_tdata <= 32'd0;
            end
            m_axis_data_tlast <= (emit_n == NFFT - 1);
            if (emit_n == NFFT - 1) begin
                emit   <= 1'b0;
                capn   <= 0;
                chk_xor<= 32'd0;
                chk_sum<= 32'd0;
            end
            else emit_n <= emit_n + 1;
        end
        else begin
            m_axis_data_tvalid <= 1'b0;
            m_axis_data_tlast  <= 1'b0;
        end
    end

endmodule
