# -*- coding: utf-8 -*-
"""生成技术文档 2.2.3 / 2.3 缺失的流程图与接口图。

为什么单独一个脚本：
    make_figures.py 里那三张是"结果类"配图（框图、对比曲线），
    这里要画的是"流程类"配图（函数流程图 + 输入输出变量），
    布局逻辑不同，混在一起会互相干扰。

本脚本产出：
    fig_flow_cmd.png       命令解码流程
    fig_flow_dds.png       信号发生流程
    fig_flow_adc.png       采集与抽取流程
    fig_flow_fft.png       自研 FFT 流程
    fig_flow_lockin.png    锁相放大流程
    fig_flow_host.png      上位机数据流
    fig_hw_iface.png       硬件接口连接示意

用法：  python make_figures_flow.py
依赖：  matplotlib + 系统中文字体
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

for _f in ["Microsoft YaHei", "SimHei"]:
    try:
        fm.findfont(_f, fallback_to_default=False)
        matplotlib.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
matplotlib.rcParams["axes.unicode_minus"] = False

OUT = os.path.dirname(os.path.abspath(__file__))

# 与 make_figures.py 完全一致的配色，保证文档里看起来是一套图
C_FPGA, C_S = "#E6F1FB", "#185FA5"
C_DSP, C_D = "#E1F5EE", "#0F6E56"
C_MEAS, C_M = "#FAEEDA", "#854F0B"
C_UI, C_U = "#EEEDFE", "#534AB7"
C_ANA, C_A = "#FAECE7", "#993C1D"
C_IO, C_I = "#F1EFE8", "#5F5E5A"
INK = "#2C2C2A"


def box(ax, x, y, w, h, text, fc, ec, fs=9.5):
    """圆角框。坐标以左下角为基准。"""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.10",
        fc=fc, ec=ec, lw=1.1, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=INK, zorder=3, linespacing=1.45)


def arrow(ax, p1, p2, c="#5F5E5A", lw=1.3, ls="-", rad=0.0, style="-|>"):
    ax.add_patch(FancyArrowPatch(
        p1, p2, arrowstyle=style, mutation_scale=13, color=c, lw=lw,
        linestyle=ls, zorder=4, shrinkA=2, shrinkB=2,
        connectionstyle="arc3,rad=%.2f" % rad))


def varlabel(ax, x, y, text, ha="center", va="center", fs=8.5, color="#5F5E5A"):
    """变量名标注。用浅底色衬一下，避免压在箭头上看不清。"""
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, color=color, zorder=6,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="none", alpha=0.92))


def canvas(w, h, title=None):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 15 * h / w)
    ax.axis("off")
    if title:
        ax.text(7.5, 15 * h / w - 0.28, title, ha="center", va="top",
                fontsize=11.5, color=INK)
    return fig, ax


def save(fig, name, note):
    plt.tight_layout(pad=0.25)
    plt.savefig(os.path.join(OUT, name), dpi=160, facecolor="white")
    plt.close()
    print("  " + note)


# =====================================================================
# 图 1  命令解码 cmd_decoder
# =====================================================================
def fig_cmd():
    fig, ax = canvas(13, 6.4, "cmd_decoder 命令解码流程（每条命令的处理路径与关键变量）")
    Y = 4.9

    box(ax, 0.20, Y, 2.05, 1.05, "uart_rx\n串口字节流\nrx_byte[7:0]", C_IO, C_I, 9)
    box(ax, 2.70, Y, 1.95, 1.05, "帧同步\n查 5A A5", C_FPGA, C_S, 9)
    box(ax, 5.10, Y + 0.30, 2.35, 0.75, "字节计数\nlen 累计", C_FPGA, C_S, 9)
    box(ax, 5.10, Y - 0.95, 2.35, 0.75, "校验和比对\nsum(B1..Bn)", C_FPGA, C_S, 9)
    box(ax, 8.00, Y, 1.95, 1.05, "命令分发\ncase(cmd[7:0])", C_DSP, C_D, 9)

    # 三路出口
    ys = [Y + 1.75, Y + 0.05, Y - 1.65]
    outs = [
        ("参数寄存器\n频率/幅度/波形", C_MEAS, C_M),
        ("脉冲命令\n复位/触发/请求", C_MEAS, C_M),
        ("静默无 ACK\n0x8A 8B 8D 8E", C_IO, C_I),
    ]
    for y, (t, fc, ec) in zip(ys, outs):
        box(ax, 10.85, y, 2.55, 0.85, t, fc, ec, 8.6)
        arrow(ax, (9.95, Y + 0.52), (10.85, y + 0.42), rad=0.0)

    arrow(ax, (2.25, Y + 0.52), (2.70, Y + 0.52))
    arrow(ax, (4.65, Y + 0.52), (5.10, Y + 0.67))
    arrow(ax, (6.28, Y + 0.30), (6.28, Y - 0.20))
    arrow(ax, (7.45, Y + 0.40), (8.00, Y + 0.52))

    varlabel(ax, 2.48, Y + 0.86, "rx_byte")
    varlabel(ax, 4.90, Y + 1.16, "B0..Bn")
    varlabel(ax, 6.28, Y - 0.36, "ok / err")
    varlabel(ax, 7.72, Y + 1.02, "cmd, pbuf")
    varlabel(ax, 9.40, Y + 1.62, "写寄存器")
    varlabel(ax, 9.40, Y + 0.30, "lk_req 等")
    varlabel(ax, 9.40, Y - 1.16, "只置标志")

    ax.text(0.20, 0.42,
            "输入：rx_byte[7:0]（串口字节流，460800-8N1）    "
            "输出：参数寄存器组（fcw / amp / wave_sel / decim / kn / …）＋ 各类脉冲命令\n"
            "校验失败的帧整帧丢弃，不产生任何副作用——这是 0x9B 那次「一次请求永久重发」的教训",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_cmd.png", "命令解码流程")


# =====================================================================
# 图 2  信号发生 dds_nco
# =====================================================================
def fig_dds():
    fig, ax = canvas(13, 6.0, "dds_nco 信号发生流程（32 位相位累加 + 查表 / 直算）")
    Y = 5.0

    box(ax, 0.20, Y, 1.95, 0.95, "频率字\nfcw[31:0]", C_IO, C_I, 9)
    box(ax, 2.55, Y, 2.15, 0.95, "相位累加器\nacc += fcw", C_DSP, C_D, 9)
    box(ax, 5.10, Y, 1.60, 0.95, "波形选择\nwave_sel", C_IO, C_I, 9)

    # 三条支路
    box(ax, 7.15, Y + 1.75, 2.55, 0.85, "正弦：查 256 点表\nsine_rom[acc[31:24]]", C_DSP, C_D, 8.8)
    box(ax, 7.15, Y + 0.05, 2.55, 0.85, "方波：取高位\nacc[31]", C_DSP, C_D, 8.8)
    box(ax, 7.15, Y - 1.65, 2.55, 0.85, "三角：高位折返\nacc 高 9 位", C_DSP, C_D, 8.8)

    box(ax, 10.45, Y + 0.90, 1.85, 0.90, "双音相加\n两路取半", C_MEAS, C_M, 8.8)
    box(ax, 10.45, Y - 1.05, 1.85, 0.90, "并串转换\nda_data[7:0]", C_MEAS, C_M, 8.8)
    box(ax, 12.85, Y + 0.90, 2.00, 0.90, "AD9708\n±5V 输出", C_ANA, C_A, 8.8)

    arrow(ax, (2.15, Y + 0.48), (2.55, Y + 0.48))
    arrow(ax, (4.70, Y + 0.62), (7.15, Y + 2.10))
    arrow(ax, (4.70, Y + 0.48), (7.15, Y + 0.48))
    arrow(ax, (4.70, Y + 0.34), (7.15, Y - 1.22))
    arrow(ax, (6.70, Y + 0.48), (7.15, Y + 1.95), c="#888780", ls="--")
    arrow(ax, (6.70, Y + 0.30), (7.15, Y - 1.40), c="#888780", ls="--")

    arrow(ax, (9.70, Y + 2.10), (10.45, Y + 1.55), rad=-0.15)
    arrow(ax, (9.70, Y + 0.48), (10.45, Y + 0.30))
    arrow(ax, (9.70, Y - 1.22), (10.45, Y - 0.60), rad=0.15)
    arrow(ax, (11.38, Y + 0.90), (11.38, Y - 0.15))
    arrow(ax, (12.30, Y + 1.35), (12.85, Y + 1.35))

    varlabel(ax, 2.35, Y + 0.78, "fcw")
    varlabel(ax, 4.85, Y + 1.05, "acc")
    varlabel(ax, 6.72, Y + 1.90, "wave_sel")
    varlabel(ax, 10.05, Y + 1.90, "sin+tri")
    varlabel(ax, 11.10, Y + 0.35, "sel")
    varlabel(ax, 12.55, Y + 1.62, "da_data")

    ax.text(0.20, 0.55,
            "输入：fcw[31:0]（频率字）、wave_sel（正弦/方波/三角/双音）、amp    "
            "输出：da_data[7:0] → AD9708（50 MHz 锁存）\n"
            "分辨率：Δf = 50 MHz / 2³² ≈ 0.0116 Hz。方波与三角由相位高位直接产生，不占额外 ROM。\n"
            "注意：DAC 在反相时钟锁存，da_data 必须是纯组合直连——中间插寄存器会让频率读数翻倍、Vpp 减半",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_dds.png", "信号发生流程")


# =====================================================================
# 图 3  采集与抽取
# =====================================================================
def fig_adc():
    fig, ax = canvas(13, 6.2, "ad_driver + timebase 采集与抽取流程（25 MSPS → 可调 fs）")
    Y = 5.2

    box(ax, 0.20, Y, 2.05, 0.95, "AD9280\n8 位并行", C_ANA, C_A, 9)
    box(ax, 2.60, Y, 2.15, 0.95, "下降沿采样\nad_cap[7:0]", C_FPGA, C_S, 9)
    box(ax, 5.10, Y, 2.15, 0.95, "5 点中值滤波\nad_med_r", C_DSP, C_D, 9)
    box(ax, 7.60, Y, 2.15, 0.95, "抽取计数\ndcnt == decim-1", C_FPGA, C_S, 9)
    box(ax, 10.10, Y, 2.15, 0.95, "写 1024 点缓存\nf_ram", C_DSP, C_D, 9)
    box(ax, 12.60, Y, 2.20, 0.95, "波形帧 / FFT\n输入", C_MEAS, C_M, 9)

    for a, b in [(2.25, 2.60), (4.75, 5.10), (7.25, 7.60), (9.75, 10.10), (12.25, 12.60)]:
        arrow(ax, (a, Y + 0.48), (b, Y + 0.48))

    # 抽取比来源
    box(ax, 5.10, Y - 1.70, 4.60, 0.80,
        "decim 来源：时基命令（T1/T2）或 波形识别自适应（wid_decim）", C_IO, C_I, 8.6)
    arrow(ax, (7.40, Y - 0.90), (8.20, Y - 0.05), rad=0.0)
    varlabel(ax, 7.30, Y - 0.42, "decim")

    # 关键变量标注
    varlabel(ax, 2.42, Y + 0.78, "ad_cap")
    varlabel(ax, 4.92, Y + 0.78, "ad_med_r")
    varlabel(ax, 9.92, Y + 0.82, "wr_idx")
    varlabel(ax, 12.42, Y + 0.80, "fs = 50MHz/decim")

    ax.text(0.20, 0.55,
            "输入：ad_cap[7:0]（偏移二进制，±128）、decim    "
            "输出：f_ram 中的 1024 点补码样点（fs = 50 MHz / decim）\n"
            "T1：decim=1000 → fs=50 kHz    T2：decim=4000 → fs=12.5 kHz    "
            "波形识别自适应：decim 按实测频率在 1023…1024 之间取\n"
            "中值滤波先于抽取，是为了在抽取前压掉宽至 2 拍的尖刺——直接对原始值做阈值判据会被毛刺带偏",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_adc.png", "采集与抽取流程")


# =====================================================================
# 图 4  自研 FFT
# =====================================================================
def fig_fft():
    fig, ax = canvas(13, 6.8, "self_fft_1024 自研 FFT 流程（10 级蝶形 + 三峰搜索 + 抛物线插值）")
    Y = 5.4

    box(ax, 0.20, Y, 1.90, 0.95, "1024 点样点\ns[9:0]", C_IO, C_I, 9)
    box(ax, 2.35, Y, 1.95, 0.95, "加窗\n(s×w)>>7", C_DSP, C_D, 9)
    box(ax, 4.55, Y, 2.10, 0.95, "位反转重排\nbit_rev", C_FPGA, C_S, 9)
    box(ax, 6.90, Y, 2.35, 0.95, "10 级蝶形\n每级 >>>1", C_DSP, C_D, 9)
    box(ax, 9.50, Y, 2.05, 0.95, "L1 取模\n|Re|+|Im|", C_MEAS, C_M, 9)
    box(ax, 11.80, Y, 1.95, 0.95, "三峰搜索\nSF / S2 / S3", C_MEAS, C_M, 9)

    for a, b in [(2.10, 2.35), (4.30, 4.55), (6.65, 6.90), (9.25, 9.50), (11.55, 11.80)]:
        arrow(ax, (a, Y + 0.48), (b, Y + 0.48))

    # 窗表与旋转因子
    box(ax, 2.35, Y - 1.55, 2.60, 0.78, "窗表 ROM\nHann/Blackman Q15", C_IO, C_I, 8.6)
    box(ax, 6.90, Y - 1.55, 2.90, 0.78, "旋转因子 ROM\n1024×16 Q1.15", C_IO, C_I, 8.6)
    arrow(ax, (3.65, Y - 0.77), (3.32, Y - 0.05))
    arrow(ax, (8.35, Y - 0.77), (8.07, Y - 0.05))
    varlabel(ax, 3.20, Y - 0.42, "win_cfg")
    varlabel(ax, 8.48, Y - 0.42, "tw_c / tw_s")

    # 插值
    box(ax, 11.80, Y - 1.55, 1.95, 0.78, "抛物线插值\nΔk 修正", C_MEAS, C_M, 8.6)
    arrow(ax, (12.77, Y - 0.05), (12.77, Y - 0.77))
    varlabel(ax, 13.35, Y - 0.42, "f_peak")

    ax.text(0.20, 0.58,
            "输入：f_ram 中的 1024 点补码样点    "
            "输出：SF/S2/S3（Hz，已插值）、每个峰的幅度\n"
            "定点口径：输入 8 位 → 加窗 Q15 → 10 级蝶形每级右移 1 位 → L1 取模。"
            "与 float64 逐 bin 对比，归一化 RMSE 0.00124（−58 dB），峰值 bin 完全一致\n"
            "插值前分辨率 48.8 Hz（1000 Hz 读作 976）；插值后 999 Hz，误差 0.1%",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_fft.png", "自研 FFT 流程")


# =====================================================================
# 图 5  锁相放大
# =====================================================================
def fig_lockin():
    fig, ax = canvas(13, 6.6, "lockin_core 数字锁相放大流程（正交解调 + 整周期累加）")
    Y = 5.0

    box(ax, 0.20, Y + 1.35, 2.10, 0.90, "ADC 样点\nad_cap", C_ANA, C_A, 9)
    box(ax, 0.20, Y - 0.35, 2.10, 0.90, "参考 NCO\n25MHz，2×fcw", C_FPGA, C_S, 9)

    box(ax, 2.80, Y + 1.85, 2.10, 0.80, "cos 参考\nQ15", C_DSP, C_D, 8.8)
    box(ax, 2.80, Y + 0.75, 2.10, 0.80, "sin 参考\nQ15", C_DSP, C_D, 8.8)

    box(ax, 5.35, Y + 1.85, 2.20, 0.80, "I 路相乘\nprod_i", C_MEAS, C_M, 8.8)
    box(ax, 5.35, Y + 0.75, 2.20, 0.80, "Q 路相乘\nprod_q", C_MEAS, C_M, 8.8)

    box(ax, 8.05, Y + 1.30, 2.30, 0.85, "整周期累加\niacc / qacc", C_DSP, C_D, 8.8)
    box(ax, 10.80, Y + 1.30, 1.95, 0.85, "锁存输出\ni_out/q_out/n", C_MEAS, C_M, 8.8)
    box(ax, 10.80, Y - 0.55, 1.95, 0.85, "上位机换算\n幅度 + 相位", C_UI, C_U, 8.8)

    arrow(ax, (1.25, Y + 1.35), (1.25, Y + 0.55), c="#888780")
    arrow(ax, (2.30, Y + 1.80), (2.80, Y + 2.25))
    arrow(ax, (2.30, Y + 0.10), (2.80, Y + 1.15))
    arrow(ax, (4.90, Y + 2.25), (5.35, Y + 2.25))
    arrow(ax, (4.90, Y + 1.15), (5.35, Y + 1.15))
    arrow(ax, (7.55, Y + 2.25), (8.05, Y + 1.90))
    arrow(ax, (7.55, Y + 1.15), (8.05, Y + 1.55))
    arrow(ax, (10.35, Y + 1.72), (10.80, Y + 1.72))
    arrow(ax, (11.77, Y + 1.30), (11.77, Y + 0.30))

    varlabel(ax, 2.55, Y + 2.02, "w_sum")
    varlabel(ax, 8.02, Y + 0.95, "m_per")
    varlabel(ax, 6.55, Y + 0.55, "N_MAX 上限")
    varlabel(ax, 12.30, Y + 0.32, "0x9B 帧")

    ax.text(0.20, 0.48,
            "输入：ad_cap（8 位样点）、参考 NCO 的正交相位、m_per（积分周期数，默认 32）    "
            "输出：i_out / q_out（48 位有符号）、n_out（累加点数）\n"
            "参考 NCO 跑 25 MHz（ADC 实际速率）并取 2 倍频率字，因此与 50 MHz 域的 DDS 严格同频。"
            "累加必须落在整数个周期上，否则残留 2f 分量会让读数持续漂移\n"
            "实测：SNR −18.8 dB 下误差 0.8%（直接测量偏 1102%）。代价是有参考频率、只能测周期信号",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_lockin.png", "锁相放大流程")


# =====================================================================
# 图 6  上位机数据流
# =====================================================================
def fig_host():
    fig, ax = canvas(13, 6.4, "上位机数据流（Python 3 + Tkinter，双线程 + 事件队列）")

    # 左侧：串口线程
    box(ax, 0.20, 6.0, 2.60, 1.05, "串口线程\nSerialWorker", C_UI, C_U, 9.2)
    box(ax, 0.20, 4.45, 2.60, 1.00, "帧解析\nStreamParser", C_FPGA, C_S, 9)
    box(ax, 0.20, 2.90, 2.60, 1.00, "协议层\nprotocol.py", C_FPGA, C_S, 9)
    box(ax, 0.20, 1.35, 2.60, 1.00, "自动重连\n断线恢复", C_IO, C_I, 9)

    # 中间：事件队列
    box(ax, 3.55, 3.55, 2.30, 1.85, "事件队列\nqueue.Queue\n\n跨线程唯一通道", C_MEAS, C_M, 9.2)

    # 右侧：界面
    box(ax, 6.65, 6.0, 2.55, 1.00, "测量行解析\nF/V/D/W/TY", C_DSP, C_D, 9)
    box(ax, 6.65, 4.60, 2.55, 1.00, "二进制帧\n波形/谱/IQ", C_DSP, C_D, 9)
    box(ax, 6.65, 3.20, 2.55, 1.00, "状态机与去抖\n3 帧一致才刷新", C_DSP, C_D, 9)
    box(ax, 6.65, 1.80, 2.55, 1.00, "提示面板\n时基/警告", C_MEAS, C_M, 9)

    box(ax, 9.95, 3.90, 2.55, 2.55,
        "Tkinter 主线程\n\n波形图\n频谱图\n瀑布图\n测量卡片", C_UI, C_U, 9.2)

    arrow(ax, (1.50, 6.00), (1.50, 5.45), c="#888780")
    arrow(ax, (1.50, 4.45), (1.50, 3.90), c="#888780")
    arrow(ax, (1.50, 2.90), (1.50, 2.35), c="#888780")
    arrow(ax, (2.80, 5.85), (3.55, 4.95))
    arrow(ax, (2.80, 2.05), (3.55, 3.75), c="#888780", ls="--")
    arrow(ax, (5.85, 5.15), (6.65, 6.35))
    arrow(ax, (5.85, 4.60), (6.65, 5.10))
    arrow(ax, (5.85, 3.90), (6.65, 3.70))
    arrow(ax, (9.20, 4.60), (9.95, 4.80))
    arrow(ax, (9.20, 2.30), (9.95, 3.95))

    varlabel(ax, 3.10, 5.55, "bytes")
    varlabel(ax, 3.10, 2.72, "stat")
    varlabel(ax, 6.20, 6.10, "measurement")
    varlabel(ax, 6.20, 5.10, "waveform / spectrum")
    varlabel(ax, 9.60, 4.20, "变量更新")

    ax.text(0.20, 0.62,
            "关键设计：串口线程**只解析、不改界面**，所有界面更新都经 queue 交给主线程。"
            "Tkinter 不是线程安全的，\n"
            "跨线程直接操作控件会在高频刷屏时随机崩溃——这条是在连续跑了半小时瀑布图之后才确认的。\n"
            "输入：COM 口字节流（460800-8N1）    输出：界面控件变量（StringVar / 绘图数据）",
            ha="left", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)
    save(fig, "fig_flow_host.png", "上位机数据流")


# =====================================================================
# 图 7  硬件接口连接示意
# =====================================================================
def fig_iface():
    fig, ax = canvas(13, 6.0, "硬件接口连接示意（成品开发板，本项目未自行绘制 PCB）")

    box(ax, 5.30, 2.60, 4.40, 3.10,
        "FPGA\nXC7A35T-2FGG484\n\nIO 电压：Bank34 LVCMOS15\nBank B16 LVCMOS33",
        C_FPGA, C_S, 10)

    # ADC
    box(ax, 0.20, 4.10, 3.30, 1.35,
        "AD9280 模块\n8 位并行 · 25 MSPS\n输入 ±5V（内部 ÷5）", C_ANA, C_A, 8.8)
    arrow(ax, (3.50, 5.05), (5.30, 5.05))
    arrow(ax, (5.30, 4.55), (3.50, 4.55))
    varlabel(ax, 4.40, 5.32, "ad_data[7:0]  →")
    varlabel(ax, 4.40, 4.28, "←  ad_clk 25MHz")

    # DAC
    box(ax, 0.20, 1.55, 3.30, 1.35,
        "AD9708 模块\n8 位并行 · 50 MHz 锁存\n输出 ±5V（电位器调幅）", C_ANA, C_A, 8.8)
    arrow(ax, (5.30, 2.45), (3.50, 2.45))
    arrow(ax, (3.50, 1.95), (5.30, 1.95))
    varlabel(ax, 4.40, 2.72, "←  da_data[7:0]")
    varlabel(ax, 4.40, 1.68, "da_clk 50MHz  →")

    # CH340
    box(ax, 11.30, 4.35, 3.45, 1.15,
        "CH340 转 USB\n460800-8N1\n仅 TX/RX，无流控", C_UI, C_U, 8.8)
    arrow(ax, (9.70, 5.05), (11.30, 5.05))
    arrow(ax, (11.30, 4.65), (9.70, 4.65))
    varlabel(ax, 10.50, 5.32, "uart_tx →")
    varlabel(ax, 10.50, 4.38, "← uart_rx")

    # 按键 LED
    box(ax, 11.30, 1.90, 3.45, 1.55,
        "KEY0 · LED0~3\n\nKEY0：切预设频率档\nLED：当前档位指示", C_IO, C_I, 8.8)
    arrow(ax, (9.70, 2.30), (11.30, 2.45))
    arrow(ax, (11.30, 2.95), (9.70, 2.90))
    varlabel(ax, 10.50, 2.72, "key / led")

    # 回环
    arrow(ax, (1.85, 1.55), (1.85, 0.95), c=C_A, lw=1.6, ls="--")
    ax.add_patch(FancyBboxPatch((0.20, 0.45), 3.30, 0.50,
                                boxstyle="round,pad=0.04,rounding_size=0.08",
                                fc=C_ANA, ec=C_A, lw=1.0, zorder=2))
    ax.text(1.85, 0.70, "短飞线回环：DAC 输出 → ADC 输入", ha="center",
            va="center", fontsize=8.6, color=INK, zorder=3)

    ax.text(5.30, 1.55,
            "回环的意义：不接任何外部仪器也能闭环自检。\n"
            "拔掉飞线即可接入外部信号源或传感器前端。",
            ha="center", va="center", fontsize=9, color="#5F5E5A", linespacing=1.7)

    ax.text(0.20, 0.15,
            "说明：本作品使用成品开发板，**未自行绘制 PCB**。上图为板上各接口与 FPGA 的连接关系，"
            "箭头方向表示信号流向，标注为关键信号线名。",
            ha="left", va="center", fontsize=9, color="#5F5E5A")
    save(fig, "fig_hw_iface.png", "硬件接口连接示意")


# =====================================================================
# 图 8  软件分层架构
# =====================================================================
def fig_swarch():
    fig, ax = canvas(13, 6.0, "软件分层架构（FPGA 侧纯 RTL，上位机侧 Python）")

    # FPGA 层
    ax.add_patch(FancyBboxPatch((0.20, 4.15), 14.60, 2.55,
                                boxstyle="round,pad=0.08,rounding_size=0.16",
                                fc="#FAFDFB", ec=C_S, lw=1.3, zorder=1))
    ax.text(0.45, 6.42, "FPGA 侧（37 个 Verilog 模块，50 MHz 单时钟域）",
            ha="left", va="center", fontsize=9.5, color=C_S, zorder=3)

    r1 = [("命令解码\ncmd_decoder", 2.0), ("信号发生\ndds_nco", 4.3),
          ("采集抽取\nad_driver", 6.6), ("参数测量\nfreq_meter", 8.9),
          ("波形识别\nwave_id", 11.2)]
    for t, x in r1:
        box(ax, x - 1.0, 5.35, 2.0, 0.78, t, C_FPGA, C_S, 8.6)

    r2 = [("时基\ntimebase", 2.0), ("波形帧\nwave_frame", 4.3),
          ("自研 FFT\nself_fft_1024", 6.6), ("IP FFT\nxfft_0", 8.9),
          ("锁相\nlockin_core", 11.2), ("谱帧\nspec_frame", 13.3)]
    for t, x in r2:
        box(ax, x - 1.0, 4.40, 2.0, 0.78, t, C_DSP, C_D, 8.6)

    # 中间协议层
    box(ax, 0.20, 3.20, 14.60, 0.72,
        "串口协议层  uart_rx / uart_tx  ·  帧头 5A A5 + 命令字 + 长度 + 负载 + 校验和  ·  27 条命令",
        C_MEAS, C_M, 9.2)

    # 上位机
    ax.add_patch(FancyBboxPatch((0.20, 0.55), 14.60, 2.35,
                                boxstyle="round,pad=0.08,rounding_size=0.16",
                                fc="#FBFAFF", ec=C_U, lw=1.3, zorder=1))
    ax.text(0.45, 2.62, "上位机侧（Python 3 + Tkinter）", ha="left",
            va="center", fontsize=9.5, color=C_U, zorder=3)

    r3 = [("串口线程\nSerialWorker", 2.2), ("协议解析\nprotocol.py", 5.2),
          ("事件队列\nqueue.Queue", 8.2), ("界面主线程\nTkinter", 11.4)]
    for t, x in r3:
        box(ax, x - 1.35, 1.55, 2.7, 0.80, t, C_UI, C_U, 8.6)
    for x in (4.1, 7.05, 10.05):
        arrow(ax, (x, 1.95), (x + 0.40, 1.95))

    arrow(ax, (7.5, 3.92), (7.5, 3.20), c="#888780", style="<|-|>")
    arrow(ax, (7.5, 3.20), (7.5, 2.35), c="#888780", style="<|-|>")

    save(fig, "fig_sw_arch.png", "软件分层架构")


if __name__ == "__main__":
    print("生成流程图与接口图：")
    fig_cmd()
    fig_dds()
    fig_adc()
    fig_fft()
    fig_lockin()
    fig_host()
    fig_iface()
    fig_swarch()
    print("完成，输出目录：", OUT)
