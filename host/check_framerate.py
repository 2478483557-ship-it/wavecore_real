# -*- coding: utf-8 -*-
"""
check_framerate.py —— 量化"波形帧实际刷新率"（评估采集死区）

原理
    连续发 0x83 请求波形，统计"每秒完整收到多少帧"。
    一帧 = 5A A5 01 04 00 + 1024 采样点 + SUM = 1030 字节
    @460800 8N1 传输约 22.4 ms；再把 1024 点采集(50kHz→20.5ms)算进去，
    二者在单口 RAM 方案下是串行的  →  合理上限 ≈ 23 帧/s（约 43 ms/帧）
    若实测明显低于此值，说明"发送期间停止采集"的死区在起作用。

判据（本工具会直接给结论）
    ≥ 20 帧/s   ：死区小，已达理论效率的 85% 以上
    10 ~ 20     ：有明显死区
    < 10        ：死区严重

用法
    双击 run_check_framerate.bat        （推荐）
    或   python check_framerate.py COM5
    可选：--seconds 15   统计时长（默认 10 秒）
"""
import argparse
import re
import sys
import time

BAUD = 460800
FRAME_LEN = 1030                      # 波形帧总长
HEAD = b"\x5A\xA5\x01"


def make_request_waveform():
    """0x83 请求波形（负载为占位 1 字节 0x00）：5A A5 83 00 01 00 84"""
    body = bytes([0x83]) + (1).to_bytes(2, "big") + b"\x00"
    return b"\x5A\xA5" + body + bytes([sum(body) & 0xFF])


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
        return None
    if len(ports) == 1:
        print("自动选择串口: %s" % ports[0].device)
        return ports[0].device
    best = sorted(ports, key=lambda p: _rank(p.device, p.description, p.hwid))[0]
    if _rank(best.device, best.description, best.hwid) == 0:
        print("自动选择串口: %s (%s)" % (best.device, best.description))
        return best.device
    print("发现多个串口，请指定：")
    for p in ports:
        print("   ", p.device, p.description)
    return None


def main():
    ap = argparse.ArgumentParser(description="测波形帧实际刷新率")
    ap.add_argument("port", nargs="?", help="串口名（缺省自动选）")
    ap.add_argument("--seconds", type=float, default=10.0, help="统计时长（默认 10 秒）")
    ap.add_argument("--freq", type=int, default=None, help="可选：先设主频 Hz")
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
        ser = serial.Serial(port, BAUD, timeout=0.05)
    except Exception as e:
        print("[错误] 打不开串口 %s: %s" % (port, e))
        print("       先关掉 GUI / 串口助手，或双击 release_com.bat。")
        return 1

    print("=" * 68)
    print(" 波形帧刷新率测试（采集死区量化）")
    print(" 串口 %s @ %d   统计 %.1f 秒" % (port, BAUD, args.seconds))
    print("=" * 68)

    # 可选：先设频率，保证有稳定信号
    if args.freq:
        body = bytes([0x85]) + (4).to_bytes(2, "big") + int(args.freq).to_bytes(4, "little")
        fr = b"\x5A\xA5" + body + bytes([sum(body) & 0xFF])
        ser.write(fr)
        print("  已设置主频 %d Hz: %s" % (args.freq, fr.hex(" ").upper()))
        time.sleep(0.4)

    ser.reset_input_buffer()

    req = make_request_waveform()
    buf = b""
    frames = 0
    bad = 0
    t0 = time.time()
    deadline = t0 + args.seconds
    last_report = t0

    # 先发一帧请求，之后每收完一帧就再请求（模拟上位机"收到就再要"）
    ser.write(req)

    while time.time() < deadline:
        # [修复] 不能用 read(2048)：一帧只有 1030 字节，永远读不满，
        #        会一直等到 timeout(50ms) 才返回 → 工具自身把上限压到 ~20 帧/s。
        #        改为"有多少读多少"，无数据时短暂让出 CPU。
        n = ser.in_waiting
        if n > 0:
            buf += ser.read(n)
        else:
            time.sleep(0.002)
            continue
        # 从缓冲里提取完整帧
        while True:
            i = buf.find(HEAD)
            if i < 0:
                if len(buf) > 8:
                    buf = buf[-8:]
                break
            if len(buf) - i < FRAME_LEN:
                if i > 0:
                    buf = buf[i:]
                break
            frame = buf[i:i + FRAME_LEN]
            # 校验：SUM(帧内最后一个字节) == 帧头之后所有字节之和
            if (sum(frame[2:-1]) & 0xFF) == frame[-1]:
                frames += 1
            else:
                bad += 1
            buf = buf[i + FRAME_LEN:]
            ser.write(req)                    # 收到一帧，立刻再要下一帧
        # 每秒报一次进度
        now = time.time()
        if now - last_report >= 1.0:
            print("   ... %4.1fs  已收 %4d 帧" % (now - t0, frames))
            last_report = now

    elapsed = time.time() - t0
    fps = frames / elapsed if elapsed > 0 else 0

    print()
    print("-" * 68)
    print("  统计时长 : %.2f s" % elapsed)
    print("  完整帧数 : %d" % frames)
    if bad:
        print("  校验失败 : %d 帧" % bad)
    print("  ★ 实际帧率 : %.1f 帧/秒" % fps)
    print("  合理上限  : 23.3 帧/秒   (传输 22.4ms + 采集 1024点@50kHz 20.5ms)")
    print("  死区占比  : %.0f%%" % max(0.0, (1.0 - fps / 23.3) * 100))
    print()

    if fps >= 20:
        print("  结论：✅ 死区小 —— 效率 >=85%%，可视为准连续采集")
    elif fps >= 10:
        print("  结论：⚠️  有明显死区 —— 建议在报告中如实标注")
    else:
        print("  结论：❌ 死区严重 —— 检查是否每次都在等上一帧发完")

    print("-" * 68)
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
