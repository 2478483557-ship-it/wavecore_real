# -*- coding: utf-8 -*-
"""
check_pretrigger.py —— 预触发（0x8F）一键板测工具

它做什么：
  1) 自己打开串口，发：停扫频 -> 方波 -> 设 20Hz -> 上升沿触发
  2) 对 0% / 25% / 50% / 75% 四档，各发一次 0x8F + 请求一次波形帧(0x83)
  3) 收到 1030 字节波形帧后，数"低电平点数"，直接判定触发点在帧内的位置

为什么用 20Hz：
  20Hz 方波在 50kHz 等效采样下周期是 2500 点，**比 1024 点的帧还长**
  -> 一帧之内最多只出现一次电平跳变，于是：
       低电平点数 = 触发点在帧内的位置（第几个点）
  这让判据变得极其干净，不用去数边沿、也不用管相位。

预期结果：
  档位     帧内低电平点数应为
  0%       0     （帧首就是触发点，整帧都在高电平）
  25%      256
  50%      512   （触发点位于帧正中，能看到触发前的半个波形）
  75%      768

用法：
  python check_pretrigger.py                 # 只有一个 USB 串口时自动选
  python check_pretrigger.py COM5
  python check_pretrigger.py COM5 --freq 20 --tol 40
  ★ 双击同目录 run_check_pretrigger.bat 即可（系统 Python 3.8 + pyserial）。

依赖：pyserial（系统 Python 3.8 已装）；不需要 matplotlib / numpy
协议：board/uart_protocol.md §2.11（0x8F 预触发，v1.21）
作者：WaveCore 队长 | 2026-10-02
"""
import argparse
import sys
import time

HEAD = b"\x5A\xA5"
BAUD = 460800

FRAME_HEAD = bytes([0x5A, 0xA5, 0x01, 0x04, 0x00])   # 波形帧头
FRAME_LEN = 2 + 1 + 2 + 1024 + 1                       # 1030
MID = 128                                              # 偏移二进制中点
PRESETS = [(0, "0%", 0), (1, "25%", 256), (2, "50%", 512), (3, "75%", 768)]


def make_frame(typ, payload=b""):
    """按协议拼一条下行帧: 5A A5 | TYPE | LEN_H LEN_L | PAYLOAD | SUM"""
    body = bytes([typ]) + len(payload).to_bytes(2, "big") + payload
    return HEAD + body + bytes([sum(body) & 0xFF])


def _port_rank(dev, desc, hwid):
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


def recv_wave_frame(ser, timeout=3.0):
    """收一帧 1030B 波形帧；返回 1024 字节采样数据或 None。"""
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < timeout:
        data = ser.read(512)
        if not data:
            continue
        buf.extend(data)
        i = buf.find(FRAME_HEAD)
        if i < 0:
            if len(buf) > 8:
                del buf[:-4]
            continue
        if i:
            del buf[:i]
        if len(buf) < FRAME_LEN:
            continue
        f = bytes(buf[:FRAME_LEN])
        if (sum(f[2:-1]) & 0xFF) == f[-1]:
            return f[5:-1]
        del buf[:FRAME_LEN]          # 校验失败: 丢掉这一帧重找
    return None


def count_low(samples):
    """数低电平点数（< 中点的采样点）。方波低电平约 0~10，高电平约 250~255。"""
    return sum(1 for b in samples if b < MID)


def main():
    ap = argparse.ArgumentParser(description="预触发 0x8F 板测（数低电平点数判触发点位置）")
    ap.add_argument("port", nargs="?", help="串口名，如 COM5（缺省自动选择）")
    ap.add_argument("--freq", type=int, default=20, help="测试信号频率 Hz（默认 20）")
    ap.add_argument("--tol", type=int, default=40, help="允许误差（点，默认 ±40）")
    args = ap.parse_args()

    try:
        import serial
    except ImportError:
        print("[错误] 没有 pyserial。请用系统 Python 3.8 运行（见 run_check_pretrigger.bat）。")
        return 1

    port = args.port or pick_port()
    if not port:
        return 1

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
    print("=" * 68)
    print(" 预触发 0x8F 板测  |  串口 %s @ %d 8N1  |  信号 %dHz 方波"
          % (port, BAUD, args.freq))
    print("=" * 68)

    # ---------- 1) 设置信号与触发 ----------
    freq_b = (int(args.freq) & 0xFFFFFFFF).to_bytes(4, "little")
    plan = [
        ("停扫频(0x8B)",      make_frame(0x8B, bytes([0]))),
        ("设 %dHz(0x85)" % args.freq, make_frame(0x85, freq_b)),
        ("方波(0x88)",        make_frame(0x88, bytes([1]))),
        ("上升沿触发(0x89)",  make_frame(0x89, bytes([1]))),
    ]
    for name, fr in plan:
        ser.write(fr)
        print("  发 %-18s : %s" % (name, fr.hex(" ").upper()))
        time.sleep(0.10)
    print("  等信号稳定 1.0 秒 ...")
    time.sleep(1.0)

    # ---------- 2) 逐档测 ----------
    print("-" * 68)
    results = []
    for level, label, expect in PRESETS:
        fr = make_frame(0x8F, bytes([level]))
        ser.write(fr)
        time.sleep(0.20)
        ser.reset_input_buffer()
        ser.write(make_frame(0x83, b"\x00"))       # 请求波形
        samples = recv_wave_frame(ser)
        if samples is None:
            results.append((label, expect, None))
            print("  %-5s 发 %s -> 没收到波形帧（超时或校验错）"
                  % (label, fr.hex(" ").upper()))
            continue
        low = count_low(samples)
        results.append((label, expect, low))
        print("  %-5s 发 %s -> 低电平点数 = %4d （预期 %4d）"
              % (label, fr.hex(" ").upper(), low, expect))
        time.sleep(0.25)

    ser.close()

    # ---------- 3) 判定 ----------
    print("-" * 68)
    print("  ===== 判定 =====")
    print("  档位    预期低点数   实测     结论")
    npass = 0
    for label, expect, low in results:
        if low is None:
            print("  %-6s  %6d      --       [FAIL] 没收到帧" % (label, expect))
            continue
        ok = abs(low - expect) <= args.tol
        npass += 1 if ok else 0
        print("  %-6s  %6d     %4d     %s" % (label, expect, low,
              "[PASS]" if ok else "[FAIL] 偏差 %d 点" % (low - expect)))

    print()
    print("  判据来源：20Hz 方波周期 2500 点 > 帧长 1024 点 → 一帧内最多一次跳变，")
    print("            所以'低电平点数'就等于触发点在帧内的位置。")
    print("  怎么读结果：")
    print("    · 四档都 PASS                      -> 预触发工作正常")
    print("    · 只有 0% PASS、其它三档低点数都是 0 -> 0x8F 没生效（固件没重建？）")
    print("    · 四档低点数几乎一样                -> 预触发档位没被识别")
    print("    · 全都收不到帧                      -> 串口/触发模式问题（先看 0x89 是否发出）")
    print("-" * 68)
    print("  把上面整块内容复制发我即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
