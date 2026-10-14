# -*- coding: utf-8 -*-
"""
check_interp.py —— 频谱插值(0x8D/0x8A 通路)一键板测工具

它做什么：
  1) 自己打开串口，依次发：停扫频 -> 设频率 -> 设波形 -> 运行自研 FFT
  2) 读回板子返回的文本行 (F/V, D/W, TY, S/A, SF/S2/S3)
  3) 把最后一次读数整理成一张表，并**直接给出判定**：插值到底生效没有

为什么需要它：
  频谱抛物线插值(USE_INTERP) 的效果是让自研通路报出的频率**更接近真值**：
      1kHz 方波基波   976  ->  999   (真值 1000)
      3 次谐波        2978 ->  2998  (真值 3000)
      5 次谐波        4980 ->  4998  (真值 5000)
  分界线很清楚：>= 990 就是插值生效，<= 988 就是没生效(旧行为)。

用法：
  python check_interp.py                 # 只有一个 USB 串口时自动选
  python check_interp.py COM5            # 指定串口
  python check_interp.py COM5 --wave 0   # 换正弦(0=正弦 1=方波 2=三角)
  python check_interp.py COM5 --secs 6   # 多读一会儿
  ★ 双击同目录 run_check_interp.bat 即可(system Python 3.8 + pyserial)。

依赖：pyserial（系统 Python 3.8 已装）；不需要 matplotlib / numpy
协议：board/uart_protocol.md §2.2(0x8A 自研FFT) §2.10(0x8D 时基)
作者：WaveCore 队长 | 2026-10-01
"""
import argparse
import re
import sys
import time

HEAD = b"\x5A\xA5"
BAUD = 460800

# ---- 板子返回的文本行(与 host/protocol.py 的正则保持一致) ----
RE_MEAS = re.compile(rb"^F=(\d{7})Hz V=(\d{4})$")
RE_PEAK = re.compile(rb"^([SA])=(\d{7})$")
RE_DUTY = re.compile(rb"^D=(\d{3}\.\d)% W=(\d{5})us$")
RE_TY = re.compile(rb"^TY=([0-3])$")
RE_FFT = re.compile(rb"^(SF|S2|S3)=(\d{7})Hz$")


def make_frame(typ, payload=b""):
    """按协议拼一条下行帧: 5A A5 | TYPE | LEN_H LEN_L | PAYLOAD | SUM"""
    body = bytes([typ]) + len(payload).to_bytes(2, "big") + payload
    return HEAD + body + bytes([sum(body) & 0xFF])


def _port_rank(dev, desc, hwid):
    """串口优先级: 0=USB 串口芯片(板子) 1=其它 2=蓝牙虚拟口（与其它工具同一套规则）"""
    s = ("%s %s %s" % (dev, desc, hwid)).lower()
    if ("ch340" in s) or ("usb-serial" in s) or ("usb serial" in s):
        return 0
    if ("bluetooth" in s) or ("\u84dd\u7259" in s) or ("bth" in s):
        return 2
    return 1


def pick_port():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("没有发现任何串口。请检查 USB 线 / 设备管理器。")
        return None
    if len(ports) == 1:
        print("自动选择串口: %s" % ports[0].device)
        return ports[0].device
    ranked = sorted(ports, key=lambda p: _port_rank(p.device, p.description, p.hwid))
    best = ranked[0]
    if _port_rank(best.device, best.description, best.hwid) == 0:
        print("自动选择串口: %s (%s)  [已跳过 %d 个非 USB 串口]"
              % (best.device, best.description, len(ports) - 1))
        return best.device
    print("发现多个串口，请指定（板子通常是 CH340）:")
    for p in ports:
        print("   ", p.device, p.description)
    return None


def judge(name, val, on_lo, on_hi, off_lo, off_hi, on_txt, off_txt):
    """给一个读数做'生效/未生效'判定，返回一行结论文本。"""
    if val is None:
        return "  %-4s : 没收到   -> 检查固件里是否真的烧了新版(或重建没成功)" % name
    if on_lo <= val <= on_hi:
        return "  %-4s = %-7d -> 插值生效   [预期 %s]  [PASS]" % (name, val, on_txt)
    if off_lo <= val <= off_hi:
        return "  %-4s = %-7d -> 还是旧值   [未生效 %s]  [FAIL]" % (name, val, off_txt)
    return "  %-4s = %-7d -> 既不是新值也不是旧值 -> 把上面的原始行发我" % (name, val)


def main():
    ap = argparse.ArgumentParser(description="频谱插值板测 (自研 FFT 通路)")
    ap.add_argument("port", nargs="?", help="串口名，如 COM5（缺省自动选择）")
    ap.add_argument("--freq", type=int, default=1000, help="信号频率 Hz（默认 1000）")
    ap.add_argument("--wave", type=int, choices=[0, 1, 2], default=1,
                    help="波形: 0=正弦 1=方波(默认) 2=三角")
    ap.add_argument("--timebase", type=int, choices=[0, 1],
                    help="顺带切时基(0x8D): 0=T1 50k 1=T2 12.5k；不给就不动 （T3/T4 已于 2026-10-14 屏蔽）")
    ap.add_argument("--secs", type=float, default=5.0, help="采集秒数（默认 5）")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("[错误] 没有 pyserial。请用系统 Python 3.8 运行（见 run_check_interp.bat）。")
        return 1

    port = args.port or pick_port()
    if not port:
        return 1

    # ---------- 1) 打开串口 ----------
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except Exception as e:
        print("[错误] 打不开串口 %s: %s" % (port, e))
        print("       常见原因：")
        print("         ① 已经开着另一个串口工具（run_gui.bat / 瀑布图 / 串口助手）")
        print("            —— 串口同一时刻只能被一个程序用；")
        print("         ② USB 线松了或插在别的口上。")
        return 1
    ser.reset_input_buffer()
    print("=" * 66)
    print(" 频谱插值板测  |  串口 %s @ %d 8N1" % (port, BAUD))
    print("=" * 66)

    # ---------- 2) 发设置帧（顺序不能乱：先停扫频，再设信号，最后触发）----------
    freq_b = (int(args.freq) & 0xFFFFFFFF).to_bytes(4, "little")
    plan = [("停扫频(0x8B)", make_frame(0x8B, bytes([0])))]
    if args.timebase is not None:
        plan.append(("时基档位(0x8D)", make_frame(0x8D, bytes([args.timebase]))))
    plan.append(("设频率 %dHz(0x85)" % args.freq, make_frame(0x85, freq_b)))
    plan.append(("设波形 %d(0x88)" % args.wave, make_frame(0x88, bytes([args.wave]))))
    trig = make_frame(0x8A, bytes([0]))
    plan.append(("运行自研FFT(0x8A)", trig))

    for name, fr in plan:
        ser.write(fr)
        print("  发 %-22s : %s" % (name, fr.hex(" ").upper()))
        time.sleep(0.08)

    # ---------- 3) 读回文本行 ----------
    print("-" * 66)
    print("  正在读回板子的上报行（%.0f 秒）..." % args.secs)
    vals = {}
    hits = {"SF": 0}
    buf = bytearray()
    t0 = time.time()
    last_trig = time.time()
    while time.time() - t0 < args.secs:
        # 自研 FFT 是"触发一次跑一轮"，这里周期性重触发，保证一直有 SF 行
        if time.time() - last_trig >= 0.5:
            ser.write(trig)
            last_trig = time.time()
        data = ser.read(512)
        if not data:
            continue
        buf.extend(data)
        while b"\n" in buf:
            raw, _, rest = bytes(buf).partition(b"\n")
            buf = bytearray(rest)
            line = raw.strip(b"\r").strip()

            m = RE_MEAS.match(line)
            if m:
                vals["F"] = int(m.group(1)); vals["V"] = int(m.group(2)); continue
            m = RE_DUTY.match(line)
            if m:
                vals["D"] = m.group(1).decode(); vals["W"] = int(m.group(2)); continue
            m = RE_TY.match(line)
            if m:
                vals["TY"] = int(m.group(1)); continue
            m = RE_PEAK.match(line)
            if m:
                vals[m.group(1).decode()] = int(m.group(2)); continue
            m = RE_FFT.match(line)
            if m:
                k = m.group(1).decode()
                vals[k] = int(m.group(2))
                if k == "SF":
                    hits["SF"] += 1
                continue
            if line:
                print("  [未知行] %r" % line[:40])
        if hits["SF"] >= 4:          # 读够 4 组就提前收工
            break
    ser.close()

    # ---------- 4) 判读 ----------
    print("-" * 66)
    print("  板子最后一次上报:")
    if "F" in vals:
        print("    测量行 : F=%07dHz V=%04d%s" %
              (vals["F"], vals.get("V", 0),
               ("  D=%s%% W=%05dus" % (vals.get("D", "---"), vals.get("W", 0)))
               if "D" in vals else ""))
        if "TY" in vals:
            ty = {0: "方波", 1: "正弦", 2: "三角", 3: "其它/未知"}.get(vals["TY"], "?")
            print("    波形类型: TY=%d (%s)" % (vals["TY"], ty))
    else:
        print("    测量行 : （没收到 —— 检查串口是否选对 / 板子是否在跑）")
    if ("S" in vals) or ("A" in vals):
        print("    IP FFT 通路(对照) : S=%07d  A=%07d" % (vals.get("S", 0), vals.get("A", 0)))

    print()
    print("  ===== 判定（自研 FFT 通路 SF/S2/S3）=====")
    print(judge("SF", vals.get("SF"), 990, 1010, 960, 988, "997~1001", "976"))
    if args.wave == 1:
        print(judge("S2", vals.get("S2"), 2990, 3006, 2960, 2988, "2995~3001", "2978"))
        print(judge("S3", vals.get("S3"), 4990, 5006, 4960, 4988, "4995~5001", "4980"))
    else:
        # 正弦：只有基波，S2/S3 应当是 0（无谐波）
        for k in ("S2", "S3"):
            if k in vals:
                v = vals[k]
                print("  %-4s = %-7d -> %s" % (k, v, "正弦无谐波，应为 0  [PASS]"
                                               if v <= 60 else "正弦却报了谐波，把原始行发我"))
    print()
    print("  判据来源：hw_analysis/probe_interp.py（数值模型，与 RTL 同口径）")
    print("  对照：插值关掉(USE_INTERP=0)时应报 976 / 2978 / 4980")
    print("        —— 两个数字对上哪个，就是那一版在跑。")
    print("-" * 66)
    print("  把上面整块内容复制发我即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
