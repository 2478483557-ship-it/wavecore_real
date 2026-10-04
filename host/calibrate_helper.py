# -*- coding: utf-8 -*-
"""
calibrate_helper.py —— 电压标定助手（万用表一点定标法）

原理（协议 v1.21 §2.8 / 0x8C）：
  FPGA 上报的 Vpp 是  V = Vpp_LSB × KN ÷ 1024   （KN 为 Q10 定标，单位：每 LSB 多少 mV）
  默认 KN = 37203（= 36.33 mV/LSB，2026-10-02 实测标定，对应模块输入端 ±5V 量程）。
  只要拿到**一个**准确的 (真实 mV, ADC 原始计数) 对应点，就能反解出真值 KN。

本工具全自动做完这四步：
  [1] 发 0x8C 1024  -> 切到“原始 LSB 模式”：此时串口上的 V= 就是 ADC 原始计数
  [2] 发 0x88 01    -> 方波（峰峰值最容易用万用表量）
  [3] 发 0x85 1Hz   -> 1Hz 方波：高低电平各持续 0.5 秒，万用表能分别读稳
  [4] 让你输入万用表读到的高/低电平 -> 自动算 KN -> 发送标定帧 -> 复验

怎么接线（只需一次）：
  万用表打到【直流电压档 V⎓】（2V 或 20V 量程都行）
  红笔 -> DA 输出端（或 AD 输入端，就是那根回环飞线任一端）
  黑笔 -> GND（板上任意接地脚）

用法：双击同目录 run_calibrate.bat；或  python calibrate_helper.py COM5
依赖：只用 pyserial
"""
import argparse
import re
import sys
import time

BAUD = 460800
HEAD = b"\x5A\xA5"


def make_frame(typ, payload=b""):
    body = bytes([typ]) + len(payload).to_bytes(2, "big") + payload
    return HEAD + body + bytes([sum(body) & 0xFF])


def _rank(dev, desc, hwid):
    s = ("%s %s %s" % (dev, desc, hwid)).lower()
    if ("ch340" in s) or ("usb-serial" in s) or ("usb serial" in s):
        return 0
    if ("bluetooth" in s) or ("bth" in s):
        return 2
    return 1


def pick_port():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("没有发现任何串口。检查 USB 线 / 设备管理器。")
        return None
    if len(ports) == 1:
        print("自动选择串口: %s" % ports[0].device)
        return ports[0].device
    best = sorted(ports, key=lambda p: _rank(p.device, p.description, p.hwid))[0]
    if _rank(best.device, best.description, best.hwid) == 0:
        print("自动选择串口: %s (%s)" % (best.device, best.description))
        return best.device
    print("发现多个串口，请指定:")
    for p in ports:
        print("   ", p.device, p.description)
    return None


def read_v(ser, timeout=2.0):
    """从串口抓一行 F=... V=xxxx，返回 V 的数值（原始计数或 mV）。"""
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        buf += ser.read(256)
        m = re.findall(rb"V=(\d{2,4})", buf)
        if m:
            return int(m[-1])
    return None


def main():
    ap = argparse.ArgumentParser(description="电压标定助手（万用表一点定标）")
    ap.add_argument("port", nargs="?", help="串口名，如 COM5（缺省自动选）")
    ap.add_argument("--freq", type=int, default=1, help="标定用方波频率 Hz（默认 1Hz）")
    ap.add_argument("--external", action="store_true",
                    help="外部信号源模式：不设板内信号，直接用信号发生器的已知幅度标定")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("[错误] 没有 pyserial，请用系统 Python 3.8 运行。")
        return 1

    port = args.port or pick_port()
    if not port:
        return 1
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except Exception as e:
        print("[错误] 打不开串口 %s: %s" % (port, e))
        print("       常见原因：别的串口工具正占着它（run_gui / 瀑布图 / 串口助手）。")
        return 1

    print("=" * 70)
    print(" WaveCore 电压标定助手   |   串口 %s @ %d" % (port, BAUD))
    print("=" * 70)
    ser.reset_input_buffer()

    plan = [("原始 LSB 模式 (0x8C 1024)",
             make_frame(0x8C, (1024).to_bytes(2, "little") + b"\x00\x00"))]
    if not args.external:
        plan += [
            ("方波 (0x88 01)",          make_frame(0x88, bytes([1]))),
            ("%dHz (0x85)" % args.freq, make_frame(0x85, int(args.freq).to_bytes(4, "little"))),
        ]
    for name, fr in plan:
        ser.write(fr)
        print("  [发] %-24s %s" % (name, fr.hex(" ").upper()))
        time.sleep(0.15)
    print()
    print("  已切到『原始 LSB 模式』：此时串口的 V= 就是 ADC 原始计数（0~255）")
    if args.external:
        print("  **外部信号源模式**：不设板内信号，请确认信号发生器已经接到")
        print("     AD 模块的输入端（回环飞线要从 AD 那头拔掉）。")
    else:
        print("  并已输出 %dHz 方波：高低电平各持续 %.2f 秒，万用表能分别读稳" %
              (args.freq, 0.5 / max(args.freq, 1)))
    time.sleep(0.6)

    n = read_v(ser, 3.0)
    if n is None:
        print("  [警告] 没读到 V= 行。检查板子是否在跑、串口是否被占用。")
    else:
        print("  当前 V = %d  （原始 ADC 计数；它要和高低电平之差 Vpp 对应）" % n)

    print()
    print("-" * 70)
    print("  下一步：万用表打到【直流电压档】，量回环飞线那一点的电压")
    print("    红笔 -> DA 输出 / AD 输入（飞线任一端）")
    print("    黑笔 -> GND")
    print("  因为方波是 %dHz，表笔不用动，等一下就能分别看到高、低两个电平" % args.freq)
    print("-" * 70)
    print()

    def ask(prompt):
        while True:
            s = input(prompt).strip().replace("V", "").replace("v", "").replace(",", ".")
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                print("   请输入数字，例如 1.080")

    vpp_mv = None
    if args.external:
        print("  信号发生器上**显示的 Vpp 就是真值**，不需要万用表。")
        while vpp_mv is None:
            s = input("    信号发生器设定的 Vpp (单位 mV，例如 1000): ").strip()
            try:
                vpp_mv = float(s)
            except ValueError:
                print("    请输入数字，例如 1000")
    else:
        print("  【方式一】先量高电平、再量低电平（推荐，最准）")
        hi = ask("    高电平读数 (单位 V，直接回车跳过): ")
        lo = None
        if hi is not None:
            lo = ask("    低电平读数 (单位 V): ")
        if hi is not None and lo is not None:
            vpp_mv = round((hi - lo) * 1000.0, 1)
            print("    -> 峰峰值 = %.1f mV" % vpp_mv)

        if vpp_mv is None:
            print()
            print("  【方式二】直接输入峰峰值")
            s = input("    峰峰值 (单位 mV，例如 1085): ").strip()
            try:
                vpp_mv = float(s)
            except ValueError:
                print("    读不到有效数字，退出。")
                return 1

    if n is None or n == 0:
        print()
        print("  [无法计算] 没拿到原始计数 N。请按上面提示确认串口读数后重试。")
        return 1

    kn = round(vpp_mv * 1024.0 / n)
    print()
    print("=" * 70)
    print("  标定计算")
    print("    真实峰峰值 V_true = %.1f mV" % vpp_mv)
    print("    ADC 原始计数 N    = %d" % n)
    print("    KN = round(V_true × 1024 ÷ N) = round(%.1f × 1024 ÷ %d) = %d"
          % (vpp_mv, n, kn))
    print("    （换算：每 LSB = KN/1024 = %.4f mV/LSB；出厂默认 37203 即 36.33）"
          % (kn / 1024.0))
    print("=" * 70)
    ok = input("  发送这条标定帧吗？(回车=发送, 输 n=不发送): ").strip().lower()
    if ok in ("n", "no"):
        print("  未发送。")
        ser.close()
        return 0

    fr = make_frame(0x8C, kn.to_bytes(2, "little") + b"\x00\x00") if kn <= 0xFFFF else None
    if fr is None:
        print("  [错误] KN=%d 超出 16 位范围（0~65535），请检查测量值。" % kn)
        ser.close()
        return 1
    ser.write(fr)
    print("  已发送: %s" % fr.hex(" ").upper())
    time.sleep(0.5)

    ser.reset_input_buffer()
    v_mv = read_v(ser, 3.0)
    if v_mv is not None:
        print()
        print("  复验：标定后串口 V = %d mV" % v_mv)
        print("        （应当接近你万用表量到的 %.0f mV）" % vpp_mv)
    print()
    print("  提醒：固件默认值已是 37203（2026-10-02 实测标定）；本次标定不落 Flash，")
    print("        断电会回到 37203。若要永久改成别的值，改 KN_DEF 后重新综合。")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
