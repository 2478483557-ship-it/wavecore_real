# -*- coding: utf-8 -*-
"""拟合实测的一阶有源低通，并出图。

数据：2026-10-26 bode_scan.py 实测（DUT = 一阶有源低通，2.2k + 4.7nF）

关键发现
--------
相位一路跑到 -228°，远超一阶低通的 -90° 极限。乍看像接错了，
其实不是：**系统本身有传播延迟**，延迟带来的相位与频率成正比，
高频段把它压过了低通本身的相位。

    实测相位 = 固定偏移 - arctan(f/fc) - 360·f·Td

三个未知量（偏移、fc、Td）一起拟合，19 个点全对上。
这不是"凑"，是模型本身对。
"""
import csv
import io
import math
import os
import statistics

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_IN = os.path.join(HERE, "..", "..", "host", "bode_dut.csv")
OUT_PNG = os.path.join(HERE, "lockin_bode_dut.png")


def load(path):
    rows = []
    with io.open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "f": int(r["freq_hz"]),
                "vpp": int(r["vpp_mv"]) if r["vpp_mv"] else None,
                "lk": float(r["lockin_mv"]) if r["lockin_mv"] else None,
                "ph": float(r["phase_deg"]) if r["phase_deg"] else None,
            })
    return rows


def apply_thru(dut, thru):
    """直通归一化：把系统自身的响应除掉，只留被测件。

    幅度：除以 thru 的锁相值（再按 1kHz 归一）
    相位：减去 thru 的相位，再展开成连续曲线
    """
    tm = {r["f"]: r for r in thru}
    ref_d, ref_t = None, None
    for r in sorted(dut, key=lambda x: x["f"]):
        t = tm.get(r["f"])
        if not t or not t["lk"] or r["lk"] is None:
            continue
        if ref_d is None:
            ref_d, ref_t = r["lk"], t["lk"]
        r["lk"] = r["lk"] / t["lk"] * ref_t      # 去掉系统幅度
        if r["ph"] is not None and t["ph"] is not None:
            r["ph"] = r["ph"] - t["ph"]
    # 相位展开
    prev = None
    for r in sorted(dut, key=lambda x: x["f"]):
        if r["ph"] is None:
            continue
        if prev is not None:
            while r["ph"] > prev + 180:
                r["ph"] -= 360
            while r["ph"] < prev - 180:
                r["ph"] += 360
        prev = r["ph"]
    return dut


def unwrap(ph_list):
    """把 -180..180 的相位展开成连续序列。"""
    out = []
    prev = None
    for p in ph_list:
        if prev is None:
            out.append(p)
        else:
            p2 = p
            while p2 > prev + 180:
                p2 -= 360
            while p2 < prev - 180:
                p2 += 360
            out.append(p2)
        prev = out[-1]
    return out


def fit(rows):
    """拟合 fc（幅度）、偏移与延迟（相位）。"""
    ok = [r for r in rows if r["lk"] and r["ph"] is not None]
    f = np.array([r["f"] for r in ok], dtype=float)
    v = np.array([r["lk"] for r in ok], dtype=float)
    p = np.array(unwrap([r["ph"] for r in ok]), dtype=float)

    # ---- fc：用低频基准 + 最小二乘（只取锁相有效的点） ----
    v0 = v[0]
    def err(logfc):
        fc = math.exp(logfc)
        model = v0 / np.sqrt(1 + (f / fc) ** 2)
        return float(np.sum((np.log(model) - np.log(v)) ** 2))
    lo, hi = math.log(500.0), math.log(200000.0)
    for _ in range(200):                     # 黄金分割
        m1 = lo + (hi - lo) * 0.382
        m2 = lo + (hi - lo) * 0.618
        if err(m1) < err(m2):
            hi = m2
        else:
            lo = m1
    fc = math.exp((lo + hi) / 2)

    # ---- 相位：线性最小二乘解 φ0 与 Td（fc 已定） ----
    base = 180.0 - np.degrees(np.arctan(f / fc))
    y = p - base
    A = np.column_stack([np.ones_like(f), f])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    phi0 = coef[0]
    td = -coef[1] / 360.0

    return f, v, p, fc, phi0, td


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    cn = False
    for fn in ("Microsoft YaHei", "SimHei", "DengXian"):
        try:
            font_manager.findfont(fn, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [fn]
            plt.rcParams["axes.unicode_minus"] = False
            cn = True
            break
        except Exception:
            pass
    T = lambda zh, en: zh if cn else en

    rows = load(CSV_IN)
    thru_path = os.path.join(HERE, "..", "..", "host", "bode_thru.csv")
    calibrated = False
    if os.path.exists(thru_path):
        rows = apply_thru(rows, load(thru_path))
        calibrated = True
    f, v, p, fc, phi0, td = fit(rows)

    print("=" * 62)
    print("  一阶有源低通 · 实测拟合")
    print("=" * 62)
    print()
    print("  直通校准  %s" % ("已做（系统响应已除掉）" if calibrated
                              else "★未做，依赖系统平坦假设"))
    print("  截止频率  fc = %.0f Hz  （标称 2.2k + 4.7nF = 15393 Hz）" % fc)
    print("  相位偏移  φ0 = %+.1f°" % phi0)
    print("  系统延迟  Td = %.2f µs  （约 %.1f 个 25MSPS 采样点）"
          % (td * 1e6, td * 25e6))
    print()

    # ---- 逐点残差 ----
    print("  %-9s %-10s %-10s %-8s %-10s %-9s" %
          ("频率", "锁相mV", "理论mV", "残差", "实测相位", "理论相位"))
    print("  " + "-" * 60)
    for r in rows:
        if not r["lk"] or r["ph"] is None:
            continue
        th = v[0] / math.sqrt(1 + (r["f"] / fc) ** 2)
        ph_th = phi0 + 180.0 - math.degrees(math.atan(r["f"] / fc)) - 360 * r["f"] * td
        # 折回 -180..180 比较
        ph_w = (ph_th + 180) % 360 - 180
        print("  %-9s %-10.0f %-10.0f %+7.1f%% %-10.0f %-9.0f"
              % ("%gk" % (r["f"] / 1000), r["lk"], th,
                 (r["lk"] / th - 1) * 100, r["ph"], ph_w))

    # ---- 出图 ----
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.8, 6.4), dpi=200, sharex=True,
        gridspec_kw={"height_ratios": [1.35, 1.0], "hspace": 0.10})

    ff = np.logspace(3, 6, 400)
    mag_th = 20 * np.log10(1.0 / np.sqrt(1 + (ff / fc) ** 2))

    ax1.semilogx(ff, mag_th, "-", color="#B4B2A9", lw=2.4,
                 label=T("理论 −20 dB/十倍频", "theory"))
    ax1.semilogx(f, 20 * np.log10(v / v[0]), "o", color="#185FA5", ms=5.5,
                 mfc="white", mew=1.4, label=T("锁相实测", "lock-in"))
    vpp_f = [r["f"] for r in rows if r["vpp"]]
    vpp_v = [r["vpp"] for r in rows if r["vpp"]]
    ax1.semilogx(vpp_f, 20 * np.log10(np.array(vpp_v) / vpp_v[0]), "s",
                 color="#C74634", ms=5, alpha=0.85,
                 label=T("Vpp 实测", "peak-to-peak"))
    ax1.axhline(-3, color="#A32D2D", ls="--", lw=1.0)
    ax1.axvline(fc, color="#A32D2D", ls=":", lw=1.0)
    ax1.annotate(T("fc = %.0f Hz" % fc, "fc = %.0f Hz" % fc),
                 xy=(fc, -3), xytext=(fc * 1.35, -0.4), fontsize=9,
                 color="#A32D2D",
                 arrowprops=dict(arrowstyle="->", color="#A32D2D", lw=1.0))
    ax1.set_ylabel(T("归一化幅度 / dB", "normalised / dB"), fontsize=10)
    ax1.set_title(T("一阶有源低通 · 实测波特图\n"
                    "2.2kΩ + 4.7nF，跟随器缓冲，DDS 扫频",
                    "First-order active LPF, measured"),
                  fontsize=11.5, pad=9)
    ax1.set_ylim(-48, 3)
    ax1.grid(True, which="both", ls=":", lw=0.5, alpha=0.5)
    ax1.legend(loc="lower left", fontsize=8.8, framealpha=0.92)

    # 标出 Vpp 失效区
    ax1.axvspan(2.2e5, 1.1e6, color="#E24B4A", alpha=0.07)
    ax1.text(4.6e5, 1.5, T("Vpp 撞本底\n读数失真", "Vpp at floor"),
             fontsize=8.2, color="#993C1D", ha="center", va="top")

    ph_th = phi0 + 180.0 - np.degrees(np.arctan(ff / fc)) - 360 * ff * td
    ax2.semilogx(ff, ph_th, "-", color="#B4B2A9", lw=2.4)
    ax2.semilogx(f, p, "o", color="#0F6E56", ms=5, mfc="white", mew=1.3)
    ax2.axhline(90, color="#888", ls="--", lw=0.9)
    ax2.text(1.05e3, 95, T("一阶反相低通极限 +90°",
                            "first-order limit"), fontsize=8,
             color="#666")
    ax2.annotate(T("高频超出 −90°，\n是系统延迟 %.2fµs 造成\n（约 8 个采样点）"
                   % (td * 1e6),
                   "beyond -90 due to %.2fus delay" % (td * 1e6)),
                 xy=(6.9e5, 62), xytext=(1.05e5, 8),
                 fontsize=8.3, color="#993C1D",
                 arrowprops=dict(arrowstyle="->", color="#993C1D", lw=0.9))
    ax2.set_ylabel(T("相位 / °", "phase / deg"), fontsize=10)
    ax2.set_xlabel(T("频率 / Hz（对数轴）", "frequency / Hz"), fontsize=10)
    ax2.set_ylim(-30, 205)
    ax2.set_yticks([180, 135, 90, 45, 0])
    ax2.grid(True, which="both", ls=":", lw=0.5, alpha=0.5)
    ax2.set_xlim(900, 1.15e6)

    fig.savefig(OUT_PNG, bbox_inches="tight", facecolor="white")
    print()
    print("  已保存:", OUT_PNG)

    # ---- 关键结论 ----
    half = [r for r in rows if r["f"] == 100000][0]
    print()
    print("=" * 62)
    print("  两条量程的交界")
    print("=" * 62)
    print("  100 kHz : 锁相 %.0f mV，真值内；Vpp %s mV" %
          (half["lk"], half["vpp"]))
    bad = [r for r in rows if r["vpp"] and r["lk"] and r["vpp"] > r["lk"] * 1.3]
    if bad:
        r0 = bad[0]
        print("  %6.0f kHz: Vpp %d mV 反而高于锁相 %.0f mV —— Vpp 已被噪声撑住"
              % (r0["f"] / 1000, r0["vpp"], r0["lk"]))
    print()
    print("  ⇒ 直接测峰峰值在 %s 附近失效，锁相仍能续到 1MHz（%.0f mV）"
          % ("300 kHz", [r for r in rows if r["f"] == 1000000][0]["lk"]))


if __name__ == "__main__":
    main()
