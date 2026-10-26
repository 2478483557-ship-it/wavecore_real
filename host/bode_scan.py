# -*- coding: utf-8 -*-
"""扫频测量二端网络的幅频 / 相频特性（波特图）。

为什么要有这个脚本
------------------
板子本身已经有全部零件：DDS 任意频率（0x85）、Vpp 测量（测量行 V=）、
锁相（0x9A/0x9B）。把它们按顺序调起来，就能给一个外部电路画波特图 ——
**不需要改一行 FPGA 代码**。

方法是真网络分析仪用的那一套：直通校准。
    第 1 遍：DAC 直连 ADC，逐点记 Vpp_ref(f)      <- 系统自身的频响
    第 2 遍：中间串上被测件，逐点记 Vpp_dut(f)
    归一化：H(f) = Vpp_dut / Vpp_ref             <- 系统响应被除掉

相位同理，只是用锁相帧里的 atan2(Q, I)。

用法
----
    # 第 1 遍：先做直通（拔掉被测件，DAC 直接连 ADC）
    python bode_scan.py thru

    # 第 2 遍：插上被测件
    python bode_scan.py dut --name "RC 220R/47nF"

    # 出图（两遍都做完才能跑）
    python bode_scan.py plot

注意事项
--------
- 不要用 0x8B 扫频：那是线性扫，波特图要**对数**频点。
- 波形帧固定 50kHz，但测量行走的是原始 25MSPS 流，
  所以扫到高频不用动时基。
- 每点要等：DDS 换频后要稳定，测量窗口本身 10ms，
  等 250ms 读 3 次取中位数比较稳。
"""
import argparse
import csv
import io
import math
import os
import re
import statistics
import sys
import time

import serial

from port_pick import pick_port
from protocol import build_command

HERE = os.path.dirname(os.path.abspath(__file__))
FREQ_HZ = 1000
PERIODS = 32

# 对数频点：1k → 1M，每十倍频程 6 点
FREQS = [1000, 1500, 2200, 3300, 4700, 6800,
         10000, 14700, 21500, 31600, 46400, 68100,
         100000, 147000, 215000, 316000, 464000, 681000,
         1000000]

# 测量行格式：F=xxxxHz V=xxxx ...（v1.17 起 V 是 4 位 mV）
RE_V = re.compile(r"V=(\d+)")


# ----------------------------------------------------------------------
# 串口读写
# ----------------------------------------------------------------------
def drain(ser, seconds):
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < seconds:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.004)
    return bytes(buf)


def read_vpp(ser):
    """从测量行取一次 Vpp（mV）。"""
    txt = drain(ser, 0.30).decode("ascii", "ignore")
    hits = RE_V.findall(txt)
    return int(hits[-1]) if hits else None


def read_lockin(ser, kn=36.33):
    """取一帧 I/Q，返回 (幅度 mVpp, 相位 deg)。"""
    ser.reset_input_buffer()
    ser.write(build_command(0x9B, b""))
    ser.flush()
    raw = drain(ser, 0.45)

    head = raw.find(b"\x5a\xa5\x03")
    if head < 0 or len(raw) < head + 22:
        return None, None
    b = raw[head:head + 22]

    i_val = int.from_bytes(b[5:11], "little", signed=True)
    q_val = int.from_bytes(b[11:17], "little", signed=True)
    cnt = int.from_bytes(b[17:21], "little")
    if not cnt:
        return None, None

    amp = 2.0 * math.hypot(i_val, q_val) / (32767.0 * cnt) * 2.0 * kn
    phase = math.degrees(math.atan2(q_val, i_val))
    return amp, phase


def measure_point(ser, freq, use_lockin, kn):
    """设频 → 等稳定 → 连读 3 次取中位数。"""
    ser.write(build_command(0x85, int(freq).to_bytes(4, "little")))
    ser.flush()
    time.sleep(0.25)          # DDS 换频 + 测量窗口刷新

    vpp_list, lk_list, ph_list = [], [], []
    for _ in range(3):
        v = read_vpp(ser)
        if v is not None and v > 0:
            vpp_list.append(v)
        if use_lockin:
            a, p = read_lockin(ser, kn)
            if a is not None and a > 0:
                lk_list.append(a)
                ph_list.append(p)
        time.sleep(0.08)

    vpp = statistics.median(vpp_list) if vpp_list else None
    lk = statistics.median(lk_list) if lk_list else None
    ph = statistics.median(ph_list) if ph_list else None
    return vpp, lk, ph


# ----------------------------------------------------------------------
# 一轮扫频
# ----------------------------------------------------------------------
def run_scan(ser, label, use_lockin, kn):
    rows = []
    print()
    print("=" * 66)
    print("  扫频：%s" % label)
    print("=" * 66)
    print("  %-10s %-12s %-12s %-10s" % ("频率", "Vpp(mV)", "锁相(mV)", "相位"))

    for i, f in enumerate(FREQS, 1):
        vpp, lk, ph = measure_point(ser, f, use_lockin, kn)
        rows.append({
            "freq_hz": f,
            "vpp_mv": vpp,
            "lockin_mv": lk,
            "phase_deg": ph,
        })
        print("  %-10s %-12s %-12s %-10s   [%d/%d]" % (
            ("%g" % f), ("%.0f" % vpp) if vpp else "--",
            ("%.1f" % lk) if lk else "--",
            ("%.0f" % ph) if ph is not None else "--",
            i, len(FREQS)))

    return rows


def save_csv(rows, path):
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "vpp_mv", "lockin_mv", "phase_deg"])
        for r in rows:
            w.writerow([r["freq_hz"],
                        "" if r["vpp_mv"] is None else "%d" % r["vpp_mv"],
                        "" if r["lockin_mv"] is None else "%.2f" % r["lockin_mv"],
                        "" if r["phase_deg"] is None else "%.1f" % r["phase_deg"]])
    print("\n  已保存: %s" % path)


def load_csv(path):
    out = []
    with io.open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({
                "freq_hz": int(r["freq_hz"]),
                "vpp_mv": int(r["vpp_mv"]) if r["vpp_mv"] else None,
                "lockin_mv": float(r["lockin_mv"]) if r["lockin_mv"] else None,
                "phase_deg": float(r["phase_deg"]) if r["phase_deg"] else None,
            })
    return out


# ----------------------------------------------------------------------
# 归一化 + 出图
# ----------------------------------------------------------------------
def do_plot(thru, dut, name, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
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
    T = (lambda zh, en: zh if cn else en)

    tmap = {r["freq_hz"]: r for r in thru}
    freqs, mag_db, ph_deg = [], [], []
    for r in dut:
        ref = tmap.get(r["freq_hz"])
        if not ref or not ref["vpp_mv"] or not r["vpp_mv"]:
            continue
        f = r["freq_hz"]
        freqs.append(f)
        mag_db.append(20 * math.log10(r["vpp_mv"] / ref["vpp_mv"]))
        if r["phase_deg"] is not None and ref["phase_deg"] is not None:
            d = r["phase_deg"] - ref["phase_deg"]
            while d > 180:
                d -= 360
            while d < -180:
                d += 360
            ph_deg.append(d)

    if not freqs:
        print("!! 没有可归一化的点：检查两遍的频点是否一致")
        return 1

    # 用低频平坦段作为 0dB 参考（去掉 R 与 ADC 输入阻抗的分压）
    flat = [m for f, m in zip(freqs, mag_db) if f <= 3300]
    offset = statistics.median(flat) if flat else 0.0
    mag_norm = [m - offset for m in mag_db]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 6.0), dpi=200, sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1.0], "hspace": 0.10})

    ax1.semilogx(freqs, mag_norm, "o-", color="#185FA5", lw=1.6, ms=5,
                 mfc="white", mew=1.4, label=T("实测", "measured"))
    ax1.axhline(-3, color="#A32D2D", ls="--", lw=1.0)
    ax1.text(freqs[-1], -3.4, T("-3 dB", "-3 dB"), ha="right", va="top",
             fontsize=9, color="#A32D2D")
    ax1.set_ylabel(T("归一化幅度 / dB", "normalised / dB"), fontsize=10)
    ax1.set_title(T("被测网络的幅频特性（直通归一化）\n%s" % name,
                    "Transfer function (thru-normalised)"),
                  fontsize=11.5, pad=9)
    ax1.grid(True, which="both", ls=":", lw=0.55, alpha=0.5)
    ax1.legend(loc="lower left", fontsize=9)

    if ph_deg and len(ph_deg) == len(freqs):
        ax2.semilogx(freqs, ph_deg, "s-", color="#0F6E56", lw=1.5, ms=4,
                     mfc="white", mew=1.2)
    else:
        ax2.text(0.5, 0.5, T("相位数据不足（锁相未开）", "no phase data"),
                 transform=ax2.transAxes, ha="center", va="center",
                 fontsize=10, color="#888")
    ax2.set_ylabel(T("相位 / °", "phase / deg"), fontsize=10)
    ax2.set_xlabel(T("频率 / Hz（对数轴）", "frequency / Hz"), fontsize=10)
    ax2.grid(True, which="both", ls=":", lw=0.55, alpha=0.5)
    ax2.set_ylim(-100, 20)
    ax2.set_yticks([0, -45, -90])

    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    print("已保存:", out_png)

    # ---- 关键指标 ----
    print()
    print("=" * 56)
    print("  测量结果")
    print("=" * 56)
    print("  频点 %d 个，低频平坦段偏移 %.1f dB（已归一）"
          % (len(freqs), offset))
    # -3dB 截止：找第一个跌破 -3dB 的点，再线性插值
    fc = None
    for i in range(1, len(mag_norm)):
        if mag_norm[i - 1] > -3 >= mag_norm[i]:
            f0, f1 = freqs[i - 1], freqs[i]
            m0, m1 = mag_norm[i - 1], mag_norm[i]
            t = (-3 - m0) / (m1 - m0)
            fc = f0 * (f1 / f0) ** t
            break
    if fc:
        print("  -3dB 截止  %.0f Hz" % fc)
    # 滚降斜率：取 -10dB 到 -20dB 两个十倍频程内拟合
    steep = [(f, m) for f, m in zip(freqs, mag_norm) if -25 < m < -8]
    if len(steep) >= 2:
        x = [math.log10(f) for f, _ in steep]
        y = [m for _, m in steep]
        n = len(x)
        sx, sy = sum(x), sum(y)
        sxx = sum(v * v for v in x)
        sxy = sum(a * b for a, b in zip(x, y))
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        print("  滚降斜率    %.1f dB/十倍频程（理论 −20）" % slope)
    return 0


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["thru", "dut", "plot"])
    ap.add_argument("--name", default="被测件", help="被测件名称，写进图标题")
    ap.add_argument("--port", default=None)
    ap.add_argument("--no-lockin", action="store_true",
                    help="不采锁相（只测幅度，快一半）")
    ap.add_argument("--kn", type=float, default=36.33,
                    help="mV/LSB，默认 36.33（已标定 37203）")
    args = ap.parse_args()

    thru_csv = os.path.join(HERE, "bode_thru.csv")
    dut_csv = os.path.join(HERE, "bode_dut.csv")
    out_png = os.path.join(HERE, "bode_plot.png")

    if args.mode == "plot":
        if not (os.path.exists(thru_csv) and os.path.exists(dut_csv)):
            print("!! 缺数据：先跑一遍 thru，再跑一遍 dut")
            return 1
        return do_plot(load_csv(thru_csv), load_csv(dut_csv),
                       args.name, out_png)

    port = pick_port(args.port)
    if port is None:
        return 1
    try:
        ser = serial.Serial(port, 460800, timeout=0)
    except Exception as e:
        print("[错误] 打不开 %s —— 上位机 GUI 还开着？先关掉。" % port)
        print("       (%s)" % str(e)[:60])
        return 1

    time.sleep(1.0)
    ser.reset_input_buffer()

    use_lockin = not args.no_lockin

    # 准备：停扫频、T1、正弦、开锁相
    ser.write(build_command(0x8B, b"\x00")); ser.flush(); time.sleep(0.15)
    ser.write(build_command(0x8D, b"\x00")); ser.flush(); time.sleep(0.15)
    ser.write(build_command(0x88, b"\x00")); ser.flush(); time.sleep(0.15)
    if use_lockin:
        ser.write(build_command(0x9C, bytes([PERIODS & 0xFF, 0])))
        ser.flush(); time.sleep(0.15)
        ser.write(build_command(0x9A, b"\x01")); ser.flush(); time.sleep(0.5)
    ser.write(build_command(0x85, FREQ_HZ.to_bytes(4, "little")))
    ser.flush(); time.sleep(0.4)

    label = "直通校准（DAC 直连 ADC）" if args.mode == "thru" else args.name
    rows = run_scan(ser, label, use_lockin, args.kn)
    save_csv(rows, thru_csv if args.mode == "thru" else dut_csv)

    if use_lockin:
        ser.write(build_command(0x9A, b"\x00"))
        ser.flush()
    ser.close()

    print()
    if args.mode == "thru":
        print("  下一步：拔掉直通飞线，串上被测件，再跑")
        print("          python bode_scan.py dut --name \"RC 220R/47nF\"")
    else:
        print("  下一步：出图")
        print("          python bode_scan.py plot --name \"RC 220R/47nF\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
