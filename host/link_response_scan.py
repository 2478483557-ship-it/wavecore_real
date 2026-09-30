# -*- coding: utf-8 -*-
"""模拟链路频响实测（本地环回，无需示波器/信号源）

回答的问题：我们的"可观察带宽"到底有多高？→ 决定时基档位（fs）能开多大。

原理
----
DDS 输出"固定幅度"的正弦，频率从 100Hz 扫到 1MHz；
读取 FPGA 上报的 Vpp(LSB)，画成"频率 - 幅度"曲线。
幅度相对低频参考值跌落 3dB（即 0.707 倍）的频率点，就是模拟链路
（DDS → AD9708 → 模块滤波/运放 → AD9280）的可用带宽上限。

为什么这条曲线可信
------------------
测量通路（freq_meter / Vpp）吃的是 **25MSPS 的 ADC 数据流**，
不受"波形上传 50kHz 抽取"的影响 → 反映的是**真实模拟带宽**。

用法
----
    python link_response_scan.py                # 自动找 CH340 串口
    python link_response_scan.py --port COM4    # 指定串口
    python link_response_scan.py --no-plot      # 不画图（只要 CSV）

输出
----
    link_response.csv   —— 频率 / Vpp 中位数 / 散度 / 实测频率 / 波形类型
    link_response.png   —— 频响曲线（matplotlib 可用时）
"""

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

import serial
from serial.tools import list_ports

from protocol import StreamParser, command_set_frequency, command_set_waveform

BAUD = 460800
CH340_VID = 0x1A86
CH340_PIDS = {0x7523, 0x5523}

# 扫频点（Hz）：低频密、高频疏；>1MHz 超出测量通路规格，不做
SWEEP_HZ = [100, 500, 1000, 2000, 5000, 10000, 20000, 30000, 50000,
            100000, 200000, 300000, 500000, 750000, 1000000]

SETTLE_SECONDS = 0.4      # 换频后等待稳定
COLLECT_SECONDS = 0.8     # 每档采集时长（约 80 行测量数据）


def pick_port(name=None):
    ports = list(list_ports.comports())
    if name:
        for p in ports:
            if p.device == name:
                return name
        raise SystemExit(f"找不到串口 {name}；当前可用：{[p.device for p in ports]}")
    ch340 = [p.device for p in ports if p.vid == CH340_VID and p.pid in CH340_PIDS]
    if not ch340:
        raise SystemExit(f"没找到 CH340 串口；当前可用：{[p.device for p in ports]}")
    return ch340[0]


def collect(ser, parser, freq_hz, seconds):
    """发送设频命令并采集若干秒，返回该档的统计量。"""
    ser.write(command_set_frequency(freq_hz))
    ser.flush()
    time.sleep(SETTLE_SECONDS)

    vpps, freqs, types = [], [], []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        line = ser.readline()
        if not line:
            continue
        for event in parser.feed(line):
            kind = event.get("type")
            if kind == "measurement":
                vpps.append(event["vpp_mv"])
                freqs.append(event["frequency_hz"])
            elif kind == "waveform_type":
                types.append(event["waveform_type"])

    if not vpps:
        return {"freq_set": freq_hz, "n": 0,
                "vpp_med": None, "vpp_min": None, "vpp_max": None,
                "f_meas": None, "ty": None}

    return {
        "freq_set": freq_hz,
        "n": len(vpps),
        "vpp_med": statistics.median(vpps),
        "vpp_min": min(vpps),
        "vpp_max": max(vpps),
        "f_meas": statistics.median(freqs),
        "ty": types[-1] if types else None,
    }


def main():
    ap = argparse.ArgumentParser(description="WaveCore 模拟链路频响实测")
    ap.add_argument("--port", help="串口号，如 COM4；缺省自动找 CH340")
    ap.add_argument("--out", default="link_response", help="输出文件名前缀")
    ap.add_argument("--no-plot", action="store_true", help="不生成 PNG 曲线")
    args = ap.parse_args()

    port = pick_port(args.port)
    print(f"串口 {port} @ {BAUD}-8N1")
    print("准备就绪：请确认板卡已上电、回环线(DA→AD)已接好。")
    input("按回车开始扫描 ...")

    rows = []
    with serial.Serial(port, BAUD, timeout=0.2) as ser:
        parser = StreamParser()
        ser.reset_input_buffer()
        ser.write(command_set_waveform(0))     # 0x88 正弦
        ser.flush()
        time.sleep(0.3)

        print("\n  设定频率      实测频率    Vpp中位数   Vpp范围      样本  类型")
        print("  " + "-" * 64)
        for f in SWEEP_HZ:
            r = collect(ser, parser, f, COLLECT_SECONDS)
            rows.append(r)
            if r["n"] == 0:
                print(f"  {f:>10} Hz     无数据！")
                continue
            print(f"  {f:>10} Hz  {r['f_meas']:>10} Hz  {r['vpp_med']:>8.0f}  "
                  f"{r['vpp_min']:>4.0f}~{r['vpp_max']:<4.0f}    {r['n']:>4}  {r['ty']}")

        # 恢复 1kHz 正弦
        ser.write(command_set_frequency(1000))
        ser.flush()
        time.sleep(0.2)

    out_csv = Path(args.out + ".csv")
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["freq_set_hz", "freq_measured_hz", "vpp_mv_median",
                    "vpp_mv_min", "vpp_mv_max", "samples", "waveform_type"])
        for r in rows:
            w.writerow([r["freq_set"], r["f_meas"], r["vpp_med"],
                        r["vpp_min"], r["vpp_max"], r["n"], r["ty"]])
    print(f"\n已保存 {out_csv.resolve()}")

    # ---- 分析：找 -3dB 点 ----
    good = [r for r in rows if r["vpp_med"]]
    if len(good) >= 3:
        ref = max(r["vpp_med"] for r in good[:4])        # 低频参考（取前 4 档最大，抗偶发）
        threshold = ref * 0.707
        f_minus3db = None
        for r in good:
            if r["vpp_med"] >= threshold:
                f_minus3db = r["freq_set"]
        print(f"\n低频参考幅度 = {ref:.0f} LSB，-3dB 门限 = {threshold:.0f} LSB")
        if f_minus3db:
            print(f"**可用带宽（-3dB）≈ {f_minus3db/1000:.0f} kHz**")
            print(f"→ 建议最高时基档位 fs ≈ {f_minus3db*2.5/1000:.2f} MHz "
                  f"（≥2.5 倍可用带宽，避免混叠）")
        else:
            print("所有档位都低于 -3dB 门限，请检查回环接线或测量通路")
        print("\n提醒：本曲线是'模拟链路'的频响；波形上传的 50kHz 抽取限制与此无关，")
        print("      提高 fs 后能看到的带宽上限由本曲线决定。")

    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            xs = [r["freq_set"] for r in good]
            ys = [r["vpp_med"] for r in good]
            err_lo = [r["vpp_med"] - r["vpp_min"] for r in good]
            err_hi = [r["vpp_max"] - r["vpp_med"] for r in good]

            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.errorbar(xs, ys, yerr=[err_lo, err_hi], marker="o",
                        linewidth=1.2, capsize=3, color="#1769aa")
            ax.set_xscale("log")
            ax.set_xlabel("Frequency (Hz)")
            ax.set_ylabel("Vpp (LSB)")
            ax.set_title("WaveCore loopback frequency response (DDS->DAC->ADC)")
            ax.grid(alpha=0.3, which="both")
            fig.tight_layout()
            out_png = Path(args.out + ".png")
            fig.savefig(out_png, dpi=150)
            print(f"已保存曲线图 {out_png.resolve()}")
        except ImportError:
            print("（未安装 matplotlib，跳过画图；CSV 已含全部数据）")

    print("\n把 CSV/PNG 发回队长：用来决定时基档位上限，并写进报告"
          "\"模拟链路频响实测\"一节。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
