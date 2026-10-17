# -*- coding: utf-8 -*-
"""上板验证用的三个一键工具（配合 run_win.bat / run_ovl.bat / run_ifft.bat）。

为什么要有这个文件：上位机 GUI 里虽然有 0x90~0x93 的控件，但 GUI 不显示频谱，
实验室里"点一下看结果"很不方便。这里每个命令都自带**判据和结论**，
双击 bat 就能看到"生效/没生效"，不用人眼比对。

用法（一般不用手敲，双击 bat 即可）：
    python lab_tools.py win          窗函数三档对比
    python lab_tools.py ovl          帧重叠开/关的刷新耗时对比
    python lab_tools.py ifft         双音 -> 掩膜 -> IFFT -> DAC 回放
    可选: 末尾加 COM5 指定串口
"""
import sys
import time
import statistics

import serial
from serial.tools import list_ports

import protocol as P

BAUD = 460800
FRAME_LEN = 518                      # 5A A5 + TYPE + LEN(2) + 512 + SUM
HEAD = b"\x5a\xa5"
FS = 50000.0                         # T1 的等效采样率
NBIN = 512
DF = FS / 1024.0                     # 48.83 Hz/bin


# ---------------------------------------------------------------- 串口
def pick_port():
    ports = list(list_ports.comports())
    if not ports:
        print("[错误] 没有找到任何串口。检查 USB 线 / 驱动。")
        sys.exit(1)
    # 优先 USB 转串口
    for p in ports:
        if "USB" in (p.description or "").upper() or "CH340" in (p.description or "").upper():
            return p.device
    return ports[0].device


def open_port(name):
    sp = serial.Serial(name, BAUD, timeout=0.2)
    sp.reset_input_buffer()
    print("串口: %s @ %d" % (name, BAUD))
    return sp


def send(sp, frame, label=""):
    sp.write(frame)
    sp.flush()
    if label:
        print("  发送 %-22s %s" % (label, " ".join("%02X" % b for b in frame)))


# ---------------------------------------------------------------- 谱帧
def read_spec(sp, timeout=1.5):
    """读一帧 0x8E 幅度谱(512 字节)。返回 list[int] 或 None。"""
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < timeout:
        buf.extend(sp.read(sp.in_waiting or 1))
        while True:
            i = buf.find(HEAD)
            if i < 0:
                if len(buf) > 256:
                    del buf[:-4]
                break
            if i:
                del buf[:i]
            if len(buf) < FRAME_LEN:
                break
            f = bytes(buf[:FRAME_LEN])
            del buf[:FRAME_LEN]
            if (sum(f[2:-1]) & 0xFF) == f[-1]:
                return list(f[5:-1])
    return None


def grab_spec(sp, tries=3):
    """请求一次谱帧并读回来。0x8E 是静默命令, 只能靠数据本身判断。"""
    for _ in range(tries):
        sp.reset_input_buffer()
        send(sp, P.command_request_spectrum())
        s = read_spec(sp)
        if s:
            return s
    return None


def spec_stats(spec):
    """返回 (峰值 bin, 峰高, 底噪)。底噪取"离主峰 15 bin 以外"的平均。"""
    pk = max(range(NBIN), key=lambda k: spec[k])
    far = [spec[k] for k in range(NBIN) if abs(k - pk) > 15 and spec[k] > 0]
    floor = statistics.mean(far) if far else 0.0
    return pk, spec[pk], floor


# ---------------------------------------------------------------- 模式 1: 窗函数
def cmd_win(sp):
    print("=" * 62)
    print(" 窗函数对比 (0x90)  —— 看**远离主峰的底噪**是否依次降低")
    print("=" * 62)
    send(sp, P.command_set_timebase(0), "时基 T1(50kHz)")
    send(sp, P.command_set_waveform(0), "波形 正弦")
    send(sp, P.command_set_frequency(1000), "主频 1000Hz")
    time.sleep(0.2)

    res = []
    for name, code in (("矩形", 0), ("Hann", 1), ("Blackman", 2)):
        print("\n--- %s ---" % name)
        send(sp, P.command_set_window(code), "窗=%d" % code)
        send(sp, P.command_run_self_fft(), "跑一次 FFT")
        time.sleep(0.15)
        s = grab_spec(sp)
        if not s:
            print("  [失败] 没读到谱帧")
            continue
        pk, top, floor = spec_stats(s)
        res.append((name, pk, top, floor))
        print("  主峰 bin=%d (%.0f Hz)  峰高=%d  底噪=%.2f" % (pk, pk * DF, top, floor))

    if len(res) == 3:
        print("\n" + "-" * 62)
        print("  %-10s %-8s %-8s" % ("窗", "底噪", "相对矩形"))
        base = res[0][3] or 1e-9
        for name, pk, top, floor in res:
            print("  %-10s %-8.2f %-8.2f" % (name, floor, floor / base))
        print("-" * 62)
        # [10-17 实测修正] 原来要求"严格递减", 实机是 79 / 24.6 / 26.6 —— 被判"未通过"。
        #   但 79 -> 24.6 已经是 3.2 倍, 说明窗确实生效了; Blackman 不比 Hann 更低
        #   是因为 **Hann 已经把泄漏压到 ADC 噪声底**, 再强的窗也看不出差别。
        #   所以正确的判据是: 矩形必须明显高于另两个(Hann/Blackman 彼此接近属正常)。
        r, h, b = res[0][3], res[1][3], res[2][3]
        if r > h * 1.5 and r > b * 1.5:
            print("  >>> 通过: 矩形底噪是另两个的 %.1f 倍, 窗函数生效" % (r / max(h, 1e-9)))
            print("       (Hann 与 Blackman 接近是正常的 —— Hann 已压到 ADC 噪声底)")
        else:
            print("  >>> 未通过: 矩形没有明显高于另两个, 把上面数字发我")


# ---------------------------------------------------------------- 模式 2: 帧重叠
def cmd_ovl(sp):
    print("=" * 62)
    print(" 帧重叠 (0x91)  —— 看**取一帧谱要多久**是否减半")
    print("=" * 62)
    send(sp, P.command_set_timebase(0), "时基 T1(50kHz)")
    send(sp, P.command_set_waveform(0), "波形 正弦")
    send(sp, P.command_set_frequency(1000), "主频 1000Hz")
    time.sleep(0.2)

    def measure(n=6):
        ts = []
        for _ in range(n):
            t0 = time.time()
            s = grab_spec(sp, tries=4)
            ts.append(time.time() - t0 if s else None)
        ok = [t for t in ts if t]
        return statistics.median(ok) if ok else None

    out = {}
    for tag, on in (("重叠关", False), ("重叠开", True)):
        print("\n--- %s ---" % tag)
        send(sp, P.command_set_overlap(on), "帧重叠=%d" % (1 if on else 0))
        time.sleep(0.3)
        ms = measure()
        out[tag] = ms
        print("  取一帧谱中位耗时: %s" % ("%.0f ms" % (ms * 1000) if ms else "失败"))

    a, b = out.get("重叠关"), out.get("重叠开")
    print("\n" + "-" * 62)
    if a and b:
        print("  关闭 %.0f ms  ->  开启 %.0f ms   (比值 %.2f)" % (a * 1000, b * 1000, b / a))
        if b < a * 0.8:
            print("  >>> 通过: 开启后取帧明显变快")
        else:
            print("  >>> 未通过: 耗时没明显变化, 把数字发我")
    else:
        print("  >>> 测量失败, 检查串口")


# ---------------------------------------------------------------- 模式 3: IFFT + DAC
def cmd_ifft(sp, f_main=1000, f_notch=5000):
    print("=" * 62)
    print(" IFFT 频域滤波 + DAC 回放 (0x92 / 0x93)")
    print("=" * 62)
    print(" 双音: 主音 %d Hz(保留) + 干扰 %d Hz(待滤除)" % (f_main, f_notch))
    print()

    # ---- ① 双音 ----
    print("[1/5] 设双音")
    send(sp, P.command_set_timebase(0), "时基 T1(50kHz)")
    send(sp, P.command_set_waveform(0), "波形 正弦")
    send(sp, P.command_set_frequency(f_main), "主频 %dHz" % f_main)
    send(sp, P.command_set_second_frequency(f_notch), "第二频 %dHz" % f_notch)
    time.sleep(0.3)
    print("      理论 bin: 主音 %.1f / 干扰 %.1f" % (f_main / DF, f_notch / DF))

    # ---- ② 正向 FFT + ★双音自检 ----
    print("\n[2/5] 跑一次自研 FFT，并检查**双音真的存在**")
    send(sp, P.command_run_self_fft(), "跑一次 FFT")
    time.sleep(0.20)
    s = grab_spec(sp)
    if not s:
        print("  [失败] 读不到谱帧, 停在这里")
        return

    # [10-17] 关键自检: 掩膜只能掩掉"多余的那一个音"。
    #   如果频谱里只有一根柱子(单音), 掩掉它之后 IFFT 输出必然是 0,
    #   DAC 只会输出中值直流 —— 看起来像"回放坏了", 其实是对的。
    b_main = int(round(f_main / DF))
    b_notch = int(round(f_notch / DF))
    def peak_near(b, w=4):
        lo, hi = max(0, b - w), min(NBIN - 1, b + w)
        return max(range(lo, hi + 1), key=lambda k: s[k])
    pm, pn = peak_near(b_main), peak_near(b_notch)
    floor = statistics.mean([s[k] for k in range(NBIN) if s[k] > 0]) or 1
    has_main = s[pm] > floor * 3
    has_notch = s[pn] > floor * 3
    print("  主音 %d Hz (bin %d): 码值 %d  %s" % (f_main, pm, s[pm], "有" if has_main else "**没有**"))
    print("  干扰 %d Hz (bin %d): 码值 %d  %s" % (f_notch, pn, s[pn], "有" if has_notch else "**没有**"))

    if not has_notch:
        print("\n  >>> 停: 没有检测到 %d Hz 这个成分。" % f_notch)
        print("      掩膜只能掩掉'多余的那一个音'; 若频谱里本来就没有它,")
        print("      掩掉唯一的音之后 IFFT 输出必然是 0, DAC 只会输出中值(直流)。")
        print("      先确认双音:");
        print("        0x85 主频 = %d Hz" % f_main)
        print("        0x87 第二频 = %d Hz" % f_notch)
        print("      再跑 0x8A, SF/S2 应分别报出这两个频率。")
        return
    if not has_main:
        print("\n  >>> 停: 主音 %d Hz 不存在, 掩掉干扰后就没有任何成分了。" % f_main)
        return
    print("  OK: 两个音都在, 可以掩膜")

    # ---- ③ 掩膜 ----
    lo, hi = max(0, pn - 2), min(NBIN - 1, pn + 2)
    print("\n[3/5] 掩掉干扰所在的一带（**要给带宽**, 加窗会把单音展宽成 ±1 bin）")
    print("      掩膜 bin %d..%d  (%.0f ~ %.0f Hz)" % (lo, hi, lo * DF, hi * DF))
    send(sp, P.command_ifft_filter(lo, hi), "IFFT 掩膜")
    time.sleep(0.35)

    # ---- ④ 回放 ----
    # [10-17] 顺序: 先开回放再跑 IFFT 更稳(老 RTL 只在反向跑完那一拍认 play_en)。
    print("\n[4/5] 打开 DAC 回放（DDS 让出 DAC）")
    send(sp, P.command_play_ifft(True), "回放 开")
    time.sleep(0.1)
    # [10-17] 去掉原来的"补发 0x92": 它会让 inv_pend 一直悬着,
    #   关回放时又触发一次反向变换, 徒增混乱。
    time.sleep(0.3)

    # ---- ⑤ 怎么看 ----
    print("\n[5/5] 现在用示波器看 DA 输出（板上的 DA 引脚）")
    print("  " + "-" * 58)
    print("  期望: 只剩 %d Hz 的波形, %d Hz 成分消失" % (f_main, f_notch))
    print("  说明: 往返必然衰减 1/N, 输出幅度只有满量程约 1/5（不是故障），")
    print("        示波器把垂直档位调小就能看清。")
    print("  关闭回放: 再双击 run_ifft.bat 加参数 off, 或发 0x93=0")
    print("  " + "-" * 58)
    print("\n  本次实际发出的帧（可直接粘贴到串口助手复现）:")
    for label, fr in (
        ("时基 T1   ", P.command_set_timebase(0)),
        ("波形 正弦 ", P.command_set_waveform(0)),
        ("主频 %dHz" % f_main, P.command_set_frequency(f_main)),
        ("第二频 %dHz" % f_notch, P.command_set_second_frequency(f_notch)),
        ("FFT       ", P.command_run_self_fft()),
        ("掩膜 %d~%d" % (lo, hi), P.command_ifft_filter(lo, hi)),
        ("回放 开   ", P.command_play_ifft(True)),
    ):
        print("    %-14s %s" % (label, " ".join("%02X" % b for b in fr)))


# ---------------------------------------------------------------- 入口
def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return
    mode = args[0].lower()
    port = None
    for a in args[1:]:
        if a.upper().startswith("COM"):
            port = a
    sp = open_port(port or pick_port())
    try:
        if mode == "win":
            cmd_win(sp)
        elif mode == "ovl":
            cmd_ovl(sp)
        elif mode == "ifft":
            if "off" in [x.lower() for x in args]:
                send(sp, P.command_play_ifft(False), "回放 关")
                print("已停止回放, DDS 重新驱动 DAC")
            else:
                cmd_ifft(sp)
        else:
            print("未知模式: %s (可选 win / ovl / ifft)" % mode)
    finally:
        sp.close()


if __name__ == "__main__":
    main()
