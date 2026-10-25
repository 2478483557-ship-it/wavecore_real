# -*- coding: utf-8 -*-
"""串口自动选择 —— 供 host/ 下的演示与自检脚本共用。

为什么单独抽出来
----------------
原来 demo_reset / demo_weak_signal / demo_sensor 都把串口写死成 "COM5"。
板子换了 USB 口、或者电脑上只有蓝牙串口时，直接抛
    SerialException: could not open port 'COM5': FileNotFoundError
而这个报错**看不出是"端口名不对"还是"板子没插"**，很容易以为是程序坏了。

规则和 check_interp.py 等已有脚本保持一致：
    CH340 / USB-Serial  -> 最优先（那就是板子）
    其它                -> 次选
    蓝牙虚拟串口         -> 最后（COM3/COM4 常常就是蓝牙，选了必然连不上）
"""
import sys


def _rank(dev, desc, hwid):
    s = ("%s %s %s" % (dev, desc, hwid)).lower()
    if ("ch340" in s) or ("usb-serial" in s) or ("usb serial" in s):
        return 0
    if ("bluetooth" in s) or ("蓝牙" in s) or ("bth" in s):
        return 2
    return 1


def pick_port(argv_port=None, verbose=True):
    """返回串口名；没有可用串口时返回 None。

    优先级：命令行传的 > 唯一的 CH340 > 唯一串口 > 报错并列出候选。
    """
    if argv_port:
        return argv_port

    try:
        from serial.tools import list_ports
    except ImportError:
        print("[错误] 没有 pyserial。请用装了 pyserial 的 Python 运行"
              "（本机通常是 Python 3.8）。")
        return None

    ports = list(list_ports.comports())
    if not ports:
        print("[错误] 没有发现任何串口。")
        print("       请检查：① USB 线是否插紧  ② 板子是否上电"
              "  ③ 设备管理器里有没有 CH340")
        return None

    ranked = sorted(ports, key=lambda p: _rank(p.device, p.description, p.hwid))
    best = ranked[0]
    if _rank(best.device, best.description, best.hwid) == 0:
        if verbose:
            others = len(ports) - 1
            note = "（已跳过 %d 个非 USB 串口）" % others if others else ""
            print("自动选择串口: %s  %s  %s" % (best.device, best.description, note))
        return best.device

    if len(ports) == 1:
        if verbose:
            print("自动选择串口: %s  %s" % (best.device, best.description))
        return best.device

    print("[错误] 没找到 CH340/USB 串口，只看到这些：")
    for p in ports:
        tag = "  <- 蓝牙虚拟口，不是板子" if _rank(p.device, p.description, p.hwid) == 2 else ""
        print("    %-6s %s%s" % (p.device, p.description, tag))
    print("       板子插上后重试，或手动指定：python 脚本名 COM6")
    return None


def open_serial(baud=460800, argv_port=None, verbose=True):
    """挑串口并打开，失败时打印人能看懂的原因。"""
    import serial
    port = pick_port(argv_port, verbose)
    if port is None:
        return None
    try:
        s = serial.Serial(port, baud, timeout=0)
        if verbose:
            print("已连接 %s @ %d" % (port, baud))
        return s
    except Exception as e:
        print("[错误] 打不开 %s：%s" % (port, e))
        print("       常见原因：① 上位机 GUI 正占着这个口（先关掉它）"
              "  ② 端口号变了")
        return None


if __name__ == "__main__":
    p = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    print("结果:", p)
