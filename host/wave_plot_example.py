# -*- coding: utf-8 -*-
"""
WaveCore 波形帧查看器 v2 —— 发 0x83 请求波形, 收到后画图并保存 wave.png
帧: 5A A5 01 04 00 | 1024 x 样点(8bit, 50kHz) | SUM
注意: 运行前请关闭串口助手(XCOM), 否则串口被占用连不上
"""
import serial
import time
import os
import sys

COM = sys.argv[1] if len(sys.argv) > 1 else "COM3"   # 用法: python wave_plot_example.py COM5
CMD = bytes([0x5A, 0xA5, 0x83, 0x00, 0x01, 0x00, 0x84])   # 请求波形
HEAD = bytes([0x5A, 0xA5, 0x01])


def try_once(ser, label):
    ser.reset_input_buffer()
    ser.write(CMD)
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 4:
        n = ser.in_waiting
        data = ser.read(n if n > 0 else 1)
        if data:
            buf += data
            print(f"     [{label}] 已收 {len(buf)} 字节", end="\r")
            i = buf.find(HEAD)
            if i >= 0 and len(buf) >= i + 5 + 1024 + 1:
                return bytes(buf[i:i + 5 + 1024 + 1]), True
    print()
    if len(buf) > 12:
        print(f"     [{label}] 未找到帧头, 收到头12字节: {buf[:12].hex(' ')}")
    return None, False


def main():
    print("[1] 打开串口", COM, "...")
    ser = serial.Serial(COM, 115200, timeout=1)
    for k in range(1, 4):
        print(f"[2] 第 {k} 次发送请求波形 0x83 ...")
        frame, ok = try_once(ser, k)
        if ok:
            npts = frame[3] * 256 + frame[4]
            samples = list(frame[5:5 + npts])
            chk = sum(frame[2:5 + npts]) & 0xFF
            print()
            print(f"[3] 收到完整帧: 类型=0x{frame[2]:02X} 点数={npts} "
                  f"校验{'OK' if chk == frame[-1] else 'FAIL'}")
            print(f"     前8点: {samples[:8]}  后8点: {samples[-8:]}")
            nz = sum(1 for s in samples if s != 0)
            print(f"     [体检] 非零点数={nz}/1024")
            print(f"     [体检] 帧头16B: {frame[0:16].hex(' ')}")
            print(f"     [体检] 帧尾4B : {frame[-4:].hex(' ')}")
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            t_sec = [i / 50_000.0 for i in range(len(samples))]
            plt.figure(figsize=(9, 4))
            plt.plot(t_sec, samples, lw=1)
            plt.xlabel("t (s)")
            plt.ylabel("ad_cap (LSB)")
            plt.grid(alpha=0.3)
            plt.title(f"WaveCore 波形帧 {len(samples)} 点 @50kHz")
            plt.tight_layout()
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wave.png")
            plt.savefig(out)
            print(f"[4] 已保存波形图: {out}")
            plt.show()
            return
    print("[!] 3 次都失败: 请确认 ①串口助手已关闭 ②已设 ≤20kHz 的频率 ③固件是最新版")


if __name__ == "__main__":
    main()
