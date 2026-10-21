# -*- coding: utf-8 -*-
"""扫频测波形识别的准确度，输出 report/wave_id_limit_2026-10-21.md 第一节那张表。

为什么需要它
------------
`wave_id` 用固定 50kHz 降采样流做形状统计。信号频率越高，每周期样点越少，
判据值离散化，正弦/三角会互相误判。这个脚本把「错误从哪个频点开始」量出来，
而不是靠感觉。

用法
----
    python host/measure_ty_vs_freq.py            # 默认扫 1k~25k
    python host/measure_ty_vs_freq.py COM5       # 指定串口
    python host/measure_ty_vs_freq.py --wide     # 加上 50k/100k

判读
----
    每行打印三种波形各自的 TY。期望值：
        正弦=1  方波=0  三角=2   (3=无法判断)

⚠️ 前提：板上 DDS 输出已回环到 ADC 输入（DAC → ADC 短接线）。
   没有回环的话三种波形读到的都是同一个信号，结果无意义。
"""
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("需要 pyserial，请用系统 Python 3.8")
    sys.exit(2)

BAUD = 460800
FS = 50000.0          # wave_id 的降采样率
EXPECT = {0: 1, 1: 0, 2: 2}   # DDS 波形号 -> 期望 TY
WNAME = {0: "正弦", 1: "方波", 2: "三角"}
TNAME = {0: "方波", 1: "正弦", 2: "三角", 3: "其他"}


def pick_port(arg):
    if arg and not arg.startswith("--"):
        return arg
    ports = [p.device for p in list_ports.comports()
             if "CH340" in (p.description or "") or "USB-SERIAL" in (p.description or "")]
    if len(ports) == 1:
        return ports[0]
    if not ports:
        print("找不到 CH340 串口，确认板子已插")
        sys.exit(2)
    print("多个候选：%s，请显式指定" % ", ".join(ports))
    sys.exit(2)


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([sum(body) & 0xFF])


def drain(ser, seconds):
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < seconds:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
    return buf.decode("ascii", "ignore")


def last_ty(text):
    found = re.findall(r"TY=(\d)", text)
    return int(found[-1]) if found else None


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    wide = "--wide" in sys.argv
    freqs = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 25000]
    if wide:
        freqs += [50000, 100000]

    ser = serial.Serial(port, BAUD, timeout=0)
    print("串口 %s @ %d 8N1" % (port, BAUD))
    time.sleep(1.0)

    # 先确认板子在出数据，否则整次测量无效（这条是踩过坑加的）
    probe = drain(ser, 1.5)
    if "F=" not in probe:
        print("\n板子没有输出，本次测量无效。")
        print("先跑 program_device.bat 烧录，再重试。")
        ser.close()
        return 2

    print()
    print("频率(Hz) | 样点/周期 | 正弦 | 方波 | 三角 | 准确率")
    print("-" * 60)

    rows = []
    try:
        for f in freqs:
            got = {}
            for w in (0, 1, 2):
                ser.write(frame(0x88, bytes([w])))
                ser.flush()
                time.sleep(0.15)
                ser.write(frame(0x85, f.to_bytes(4, "little")))
                ser.flush()
                time.sleep(0.6)
                ser.reset_input_buffer()
                time.sleep(0.9)
                got[w] = last_ty(drain(ser, 1.4))

            hits = sum(1 for w in (0, 1, 2) if got.get(w) == EXPECT[w])
            cells = []
            for w in (0, 1, 2):
                v = got.get(w)
                mark = "" if v == EXPECT[w] else "*"
                cells.append("%s%s" % ("-" if v is None else v, mark))
            print("%8d | %9.1f | %4s | %4s | %4s | %d/3" % (
                f, FS / f, cells[0], cells[1], cells[2], hits))
            rows.append((f, hits, dict(got)))

        print()
        print("带 * 的是判错。'其他'=3 表示系统自己也不确定。")
        ok_until = [f for f, h, _ in rows if h == 3]
        print("三档全对的最高频率：%s Hz" % (max(ok_until) if ok_until else "无"))
        print()
        print("理论：spp = 50000/F，需 ≥32 才能稳定区分正弦与三角")
        print("      → 上限约 %.0f Hz" % (FS / 32))
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
