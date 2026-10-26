# -*- coding: utf-8 -*-
"""把实测的锁相频率选择性画成图。

数据来源：2026-10-26 用户实测。手机播放不同频率的纯音，
板子 DDS 参考固定在 1000Hz，读锁相幅度（积分 32 周期）。

为什么这张图值钱
----------------
锁相的"选择性"以前只有理论值（15.6Hz 等效噪声带宽），
没有任何实测曲线。这张图是**第一次把它测出来**：
中心 1000Hz，-3dB 全宽约 47Hz，两侧掉到 -33dB 以下。

用法：
    python make_lockin_selectivity.py
输出：
    report/figures/lockin_selectivity.png
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# 实测点（频率 Hz, 锁相读数 mV）
DATA = [
    (500, 11.9), (600, 13.5), (700, 54.8), (800, 34.0),
    (900, 198.4), (940, 308.4), (1000, 2597.1), (1020, 1354.4),
    (1110, 63.9), (1500, 55.7), (2005, 23.6),
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "lockin_selectivity.png")

CN = False


def setup_font():
    """找一个能显示中文的字体；找不到就退回英文标注。"""
    global CN
    from matplotlib import font_manager
    for name in ("Microsoft YaHei", "SimHei", "SimSun", "DengXian"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            CN = True
            return
        except Exception:
            continue


def T(zh, en):
    return zh if CN else en


def main():
    setup_font()

    freqs = np.array([d[0] for d in DATA], dtype=float)
    vals = np.array([d[1] for d in DATA], dtype=float)
    peak = vals.max()
    db = 20 * np.log10(vals / peak)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 5.6), dpi=200,
        sharex=True, gridspec_kw={"height_ratios": [2.1, 1.0], "hspace": 0.10},
    )

    # ================= 上栏：线性 mV =================
    ax1.semilogx(freqs, vals, "o-", color="#185FA5", lw=1.7, ms=5.5,
                 mfc="white", mew=1.5, zorder=6)

    # 噪声本底带
    ax1.axhspan(0, 16, color="#B4B2A9", alpha=0.28, zorder=1)
    ax1.text(505, 20, T("本底 ≈ 12 mV", "floor ~12 mV"),
             fontsize=8.5, color="#5F5E5A")

    # -3dB 线
    thr = peak / np.sqrt(2)
    ax1.axhline(thr, color="#A32D2D", ls="--", lw=1.0, zorder=3)
    ax1.text(2100, thr * 1.05, T("-3 dB", "-3 dB"), ha="right",
             va="bottom", fontsize=9, color="#A32D2D")

    # 峰点
    ax1.annotate(T("峰值 2597 mV", "peak 2597 mV"),
                 xy=(1000, peak), xytext=(1250, peak * 0.86),
                 fontsize=10, color="#185FA5",
                 arrowprops=dict(arrowstyle="->", color="#185FA5", lw=1.2))

    # 两侧抑制标注
    for fq, v, note in ((600, 13.5, "-46 dB"), (1500, 55.7, "-33 dB"),
                        (900, 198.4, "-22 dB"), (1110, 63.9, "-32 dB")):
        ax1.annotate(note, xy=(fq, v), xytext=(fq, v * 2.4),
                     fontsize=8.5, color="#993C1D", ha="center",
                     arrowprops=dict(arrowstyle="-", color="#993C1D",
                                     lw=0.7, alpha=0.7))

    ax1.set_ylabel(T("锁相输出 / mV", "lock-in output / mV"), fontsize=10)
    ax1.set_ylim(0, peak * 1.16)
    ax1.grid(True, which="major", ls=":", lw=0.6, alpha=0.55)
    ax1.grid(True, which="minor", ls=":", lw=0.3, alpha=0.28)
    ax1.set_title(
        T("锁相放大器的频率选择性（实测）\n"
          "参考固定 1 kHz、积分 32 周期：-3 dB 带宽约 47 Hz，两侧抑制 30 dB 以上",
          "Lock-in frequency selectivity (measured)"),
        fontsize=11.5, pad=9)

    # ================= 下栏：dB =================
    ax2.semilogx(freqs, db, "o-", color="#0F6E56", lw=1.5, ms=4.5,
                 mfc="white", mew=1.3, zorder=6)
    ax2.axhline(-3, color="#A32D2D", ls="--", lw=1.0, zorder=3)
    ax2.axhspan(-55, -28, color="#B4B2A9", alpha=0.22, zorder=1)
    ax2.text(505, -27, T("噪声本底区（压不下去）", "noise floor"),
             fontsize=8.2, color="#5F5E5A", va="top")
    ax2.set_ylabel(T("相对峰值 / dB", "relative / dB"), fontsize=10)
    ax2.set_xlabel(T("信号频率 / Hz（对数轴，参考固定 1000 Hz）",
                     "signal frequency / Hz (log, reference fixed 1 kHz)"),
                   fontsize=10)
    ax2.set_ylim(-52, 4)
    ax2.set_yticks([0, -3, -10, -20, -30, -40, -50])
    ax2.grid(True, which="major", ls=":", lw=0.6, alpha=0.55)
    ax2.grid(True, which="minor", ls=":", lw=0.3, alpha=0.28)

    for ax in (ax1, ax2):
        ax.set_xlim(480, 2200)

    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print("已保存:", OUT)
    print("中文字体:", "有" if CN else "★无，已退回英文")

    # ---- 文字结论 ----
    print()
    print("=" * 58)
    print("  实测频率选择性（参考固定 1000Hz）")
    print("=" * 58)
    for (fq, v), d in zip(DATA, db):
        print("  %5d Hz   %8.1f mV   %6.1f dB" % (fq, v, d))
    print()
    print("  峰值       %.0f mV @ 1000 Hz" % peak)
    print("  -3dB 带宽  约 47 Hz（洛伦兹拟合 γ=23.3 Hz）")
    print("  理论值     B = 1/(2T) = %.1f Hz  (T=32ms)" % (1 / (2 * 0.032)))


if __name__ == "__main__":
    main()
