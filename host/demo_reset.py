# -*- coding: utf-8 -*-
"""录制前一键复位 —— 把板子恢复到"干净起点"。

为什么要脚本而不是手敲帧：
    手算校验和出过三次错（这次写操作单又错了两处）。
    现场录制时更没时间核对，直接跑脚本最稳。

复位做什么：
    关噪声、关锁相、时基回 T1、波形回正弦、频率回 1kHz、
    识别来源回自动、标定回默认 KN。

用法：
    python demo_reset.py            # 默认 COM5
    python demo_reset.py COM3
"""
import sys
import time

import serial

from protocol import (
    build_command,
    command_set_ty_source,
    command_set_timebase,
    command_set_vpp_cal,
    DEFAULT_VPP_KN,
)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    s = serial.Serial(port, 460800, timeout=0)
    time.sleep(1.2)
    s.reset_input_buffer()

    steps = [
        ("关噪声",        build_command(0x99, bytes([0, 0]))),
        ("关锁相",        build_command(0x9A, bytes([0]))),
        ("时基 T1",       command_set_timebase(0)),
        ("波形=正弦",     build_command(0x88, bytes([0]))),
        ("频率=1kHz",     build_command(0x85, (1000).to_bytes(4, "little"))),
        ("识别=自动",     command_set_ty_source(2)),
        ("标定=默认KN",   command_set_vpp_cal(DEFAULT_VPP_KN)),
        ("关自适应选窗",  build_command(0x97, bytes([0]))),
    ]

    print("复位到演示起点：")
    for name, frame in steps:
        s.write(frame)
        s.flush()
        time.sleep(0.25)
        print("  %-14s %s" % (name, " ".join("%02X" % b for b in frame)))

    # 收 1.5 秒的数据再判断。
    # 原来写成 `s.read(...) if s.in_waiting else ""` —— in_waiting 那一瞬间
    # 可能刚好是 0，于是直接判"没回显"，误报。
    time.sleep(0.8)
    s.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 1.5:
        n = s.in_waiting
        if n:
            buf += s.read(n)
    echo = bytes(buf).decode("ascii", "ignore")
    s.close()

    print()
    if "F=0001000" in echo:
        print("  ✓ 板子已在 1kHz 正弦，可以开录")
    elif echo:
        print("  板子有响应，但没看到 F=0001000，抽查一下：")
        for line in echo.split("\r\n")[:4]:
            if line.strip():
                print("   ", line.strip())
    else:
        print("  [注意] 没收到回显，检查串口是不是被上位机占用了")


if __name__ == "__main__":
    main()
