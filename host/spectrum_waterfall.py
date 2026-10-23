# -*- coding: utf-8 -*-
"""
spectrum_waterfall.py —— 0x8E 幅度谱帧接收 + 频谱图/瀑布图（演示用独立小工具）

用途：连续请求 FPGA 的幅度谱（协议 v1.18 §2.9），画出
      ① 实时频谱（512 点柱状/折线，0~25kHz）
      ② 瀑布图（时间纵轴滚动，扫频时会出现一条斜线 —— 演示王炸画面）

用法：
  python spectrum_waterfall.py COM5                 # 指定串口
  python spectrum_waterfall.py                      # 只有一个串口时自动选
  python spectrum_waterfall.py COM5 --interval 0.1  # 请求间隔(秒), 默认 0.15
  python spectrum_waterfall.py --demo --save demo.png   # 无板自测 + 存图

演示常用（[10-01 新增] 开机自动先发设置帧，省得再开别的串口工具）：
  python spectrum_waterfall.py COM5 --freq 1000 --wave 1 # 先放 1kHz 方波 -> 看三根谱线
  python spectrum_waterfall.py COM5 --sweep --wave 1     # 启动扫频(0x8B) -> 瀑布出斜线
  ⚠️ 串口只能被一个程序占用：跑本工具时请关掉 run_gui.bat / 串口助手。

依赖：pyserial / matplotlib / numpy
      ★ 用**系统 Python 3.8**（已装齐）：见 run_waterfall.bat（双击即用）
协议：board/uart_protocol.md §2.9（帧: 5A A5 02 02 00 + 512B + SUM, 518 字节）
作者：WaveCore 队长 | 2026-09-30
"""
import argparse
import queue
import sys
import threading
import time

import numpy as np

FRAME_HEAD = bytes([0x5A, 0xA5, 0x02, 0x02, 0x00])
N_BINS = 512
FRAME_LEN = 2 + 1 + 2 + N_BINS + 1          # 518
DF_HZ = 50000.0 / 1024.0                    # 48.828 Hz / bin (T1 默认)
# [2026-10-14 收窄] 只开放 T1/T2；T3/T4 实机无响应，已屏蔽。
#   恢复办法见 host/protocol.py 里 TIMEBASE_SAMPLE_RATES 上方的注释。
TB_FS = {0: 50000.0, 1: 12500.0}   # [0x8D] 时基档位 -> 等效采样率 Hz
CMD_SPEC = bytes([0x5A, 0xA5, 0x8E, 0x00, 0x00, 0x8E])
HIST = 240                                  # 瀑布图保留多少帧


def make_frame(typ, payload=b""):
    """按协议拼一条下行帧: 5A A5 | TYPE | LEN_H LEN_L | PAYLOAD | SUM"""
    body = bytes([typ]) + len(payload).to_bytes(2, "big") + payload
    return b"\x5A\xA5" + body + bytes([sum(body) & 0xFF])


# ---------------------------------------------------------------- 帧解析
class FrameParser:
    """字节流 -> 518B 谱帧（搜帧头 + 长度 + 校验和）。"""

    def __init__(self):
        self.buf = bytearray()
        self.n_ok = 0
        self.n_bad = 0

    def feed(self, data):
        out = []
        self.buf.extend(data)
        while True:
            i = self.buf.find(FRAME_HEAD)
            if i < 0:
                if len(self.buf) > 512:
                    del self.buf[:-8]           # 只留可能的半个帧头
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < FRAME_LEN:
                break
            f = bytes(self.buf[:FRAME_LEN])
            if (sum(f[2:-1]) & 0xFF) == f[-1]:
                out.append(f[5:-1])             # 512 字节负载
                self.n_ok += 1
            else:
                self.n_bad += 1
            del self.buf[:FRAME_LEN]
        return out


# ---------------------------------------------------------------- 数据源
class DemoSource(threading.Thread):
    """无板自测：合成"扫频 + 3 次谐波 + 噪声"的谱帧，10 帧/s。"""

    def __init__(self, out_q, stop_evt):
        super().__init__(daemon=True)
        self.q = out_q
        self.stop = stop_evt
        self.n = 0

    def run(self):
        while not self.stop.is_set():
            i = self.n
            bins = np.zeros(N_BINS)
            k0 = 20 + int(60 * (1 + np.sin(i * 0.05)))       # 峰在 bin20~140 间摆动
            for k, a in ((k0, 200), (3 * k0, 130), (5 * k0, 100)):
                if 0 < k < N_BINS:
                    bins[k] = a
            bins += np.random.rand(N_BINS) * 30              # 噪声底
            row = np.clip(bins, 0, 255).astype(np.uint8)
            self.q.put(row.tobytes())
            self.n += 1
            time.sleep(0.1)


class BoardSource(threading.Thread):
    """有板：每 interval 秒发一次 0x8E，收 518B 帧。"""

    def __init__(self, port, interval, out_q, stop_evt, setup_frames=()):
        super().__init__(daemon=True)
        import serial  # 延迟导入：--demo 时不依赖串口
        self.serial_mod = serial
        self.port = port
        self.interval = interval
        self.q = out_q
        self.stop = stop_evt
        self.parser = FrameParser()
        self.t0 = time.time()
        self.n_frames = 0
        self.setup_frames = tuple(setup_frames)   # [10-01] 开串口后先发的设置帧(频率/波形/扫频)

    def run(self):
        try:
            self.ser = self.serial_mod.Serial(self.port, 460800, timeout=0.05)
        except Exception as e:
            print("[错误] 打不开串口 %s: %s" % (self.port, e))
            # [10-01] CH340 被占用时报的是 "设备没有发挥作用"(Windows error 31),
            #   很容易被误读成"板子坏了"。这里把两种最常见原因直接写清楚。
            print("       常见原因：")
            print("         ① 已经开着**另一个**本工具窗口（标题: WaveCore 频谱/瀑布 (0x8E)）,")
            print("            或 run_gui.bat / 串口助手 占着它 —— 串口同一时刻只能被一个程序用；")
            print("         ② 板子 USB 线松了/插在别的口上（拔插一次再试）。")
            self.stop.set()
            return
        for fr in self.setup_frames:              # [10-01] 先设信号(0x85/0x88/0x8B)
            try:
                self.ser.write(fr)
                time.sleep(0.05)
            except Exception as e:
                print("[警告] 设置帧发送失败:", e)
        last_req = 0.0
        while not self.stop.is_set():
            now = time.time()
            if now - last_req >= self.interval:
                try:
                    self.ser.write(CMD_SPEC)
                except Exception as e:
                    print("[错误] 串口写失败:", e)
                    self.stop.set()
                    break
                last_req = now
            try:
                data = self.ser.read(256)
            except Exception as e:
                print("[错误] 串口读失败:", e)
                self.stop.set()
                break
            for pl in self.parser.feed(data):
                self.q.put(pl)
                self.n_frames += 1

    def stats(self):
        return self.parser.n_ok, self.parser.n_bad, self.n_frames


def _port_rank(dev, desc, hwid):
    """串口优先级: 0=USB 串口芯片(板子) 1=其它 2=蓝牙虚拟口
    [10-01 新增] 本机常年挂着 COM3/COM4 两个蓝牙虚拟串口, 双击时老是"发现多个串口"。
    板子固定是 CH340, 所以按描述/硬件 ID 打分, USB 串口优先、蓝牙排最后。"""
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
        print("没有发现串口。用 --demo 可以无板自测。")
        return None
    if len(ports) == 1:
        print("自动选择串口:", ports[0].device)
        return ports[0].device
    ranked = sorted(ports, key=lambda p: _port_rank(p.device, p.description, p.hwid))
    best = ranked[0]
    if _port_rank(best.device, best.description, best.hwid) == 0:
        print("自动选择串口: %s (%s)   [已跳过 %d 个非 USB 串口]"
              % (best.device, best.description, len(ports) - 1))
        return best.device
    print("发现多个串口，请指定（板子通常是 CH340）：")
    for p in ports:
        print("   ", p.device, p.description)
    return None


# ---------------------------------------------------------------- 显示
def main():
    ap = argparse.ArgumentParser(description="0x8E 幅度谱 -> 频谱图/瀑布图")
    ap.add_argument("port", nargs="?", help="串口名，如 COM5（缺省自动选择）")
    ap.add_argument("--interval", type=float, default=0.15, help="请求间隔秒（默认 0.15）")
    ap.add_argument("--demo", action="store_true", help="无板演示模式（合成数据）")
    ap.add_argument("--save", metavar="PNG", help="不回显，跑 200 帧后存图（自测用）")
    ap.add_argument("--dump", metavar="TXT",
                    help="不回显，跑 200 帧后把最后一帧的 512 个幅度码存成文本（诊断用）")
    ap.add_argument("--freq", type=int, metavar="HZ", help="开机先设信号频率(0x85)，如 1000")
    ap.add_argument("--wave", type=int, choices=[0, 1, 2], metavar="N",
                    help="开机先设波形(0x88)：0=正弦 1=方波 2=三角")
    ap.add_argument("--timebase", type=int, choices=sorted(TB_FS), metavar="N",
                    help="开机先设时基(0x8D)：0=T1 50k 1=T2 12.5k 2=T3 6.25MHz 3=T4 12.5MHz（2/3 为高频频谱档）")
    ap.add_argument("--sweep", action="store_true",
                    help="开机先启动扫频(0x8B, 1k->20k) —— 瀑布出斜线")
    ap.add_argument("--sweep-stop", action="store_true",
                    help="开机先**停止**扫频(0x8B payload 0) —— 看静态谱线前必做")
    args = ap.parse_args()

    # [10-01 BUGFIX] import 必须在**函数最前面无条件**执行:
    #   之前写成 if args.save: import matplotlib  ->  Python 认为 matplotlib 是整个
    #   main() 的**局部变量**, 于是在不带 --save 的那条路(双击直接跑)上,
    #   下面这句 rcParams 就报 UnboundLocalError: local variable 'matplotlib'
    #   referenced before assignment。
    #   教训: 条件分支里 import = 埋雷; 而且"只测了 --demo --save 分支"不等于测过主路径。
    import matplotlib
    if args.save or args.dump:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    stop_evt = threading.Event()
    q = queue.Queue(maxsize=64)

    if args.demo or args.save or args.dump:
        src = DemoSource(q, stop_evt)
        src_name = "演示数据（无板）"
    else:
        port = args.port or pick_port()
        if not port:
            return 1
        setup = []
        if args.sweep_stop:
            # [10-01] 扫频一旦开始会一直循环(设单音频率并不能关掉它, 实测确认),
            #   所以"看静态谱"这类脚本必须先显式停扫频。
            setup.append(make_frame(0x8B, bytes([0])))
        if args.timebase is not None:
            setup.append(make_frame(0x8D, bytes([args.timebase])))
        if args.freq is not None:
            setup.append(make_frame(0x85, (int(args.freq) & 0xFFFFFFFF).to_bytes(4, "little")))
        if args.wave is not None:
            setup.append(make_frame(0x88, bytes([args.wave])))
        if args.sweep:
            setup.append(make_frame(0x8B, bytes([1])))
        for fr in setup:
            print("  先发设置帧:", fr.hex(" ").upper())
        if not setup:
            print("  [提示] 未设置信号：上电默认是 100kHz 预设，而自研谱的 fs=50kHz（会混叠）。")
            print("         想让谱线有意义，请加参数，例如： --freq 1000 --wave 1  （1kHz 方波）")
        src = BoardSource(port, args.interval, q, stop_evt, setup)
        src_name = "串口 %s" % port
    src.start()

    # ---- 图 ----
    fig = plt.figure("WaveCore 频谱/瀑布 (0x8E)", figsize=(10, 6.6))
    fig.subplots_adjust(hspace=0.42, left=0.09, right=0.97, top=0.90, bottom=0.09)
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)

    # [0x8D] 频率轴随当前时基档位缩放(谱帧本身不带 fs, 由本工具自己记住自己设的档位)
    fs_hz = TB_FS[args.timebase] if args.timebase is not None else 50000.0
    df_hz = fs_hz / 1024.0
    xmax_khz = N_BINS * df_hz / 1000.0
    print("  频率轴: 0~%.2f kHz (%.2f Hz/bin, 时基 T%d)" % (xmax_khz, df_hz, (args.timebase or 0) + 1))
    xkhz = np.arange(N_BINS) * df_hz / 1000.0
    line, = ax1.plot(xkhz, np.zeros(N_BINS), lw=1.2)
    ax1.set_xlim(0, xmax_khz)
    ax1.set_ylim(0, 260)
    ax1.set_xlabel("频率 (kHz)")
    ax1.set_ylabel("幅度码 (对数)")
    ax1.grid(alpha=0.3)
    pktxt = ax1.text(0.99, 0.95, "", ha="right", va="top", transform=ax1.transAxes)

    wf = np.zeros((HIST, N_BINS), dtype=np.uint8)
    img = ax2.imshow(wf, aspect="auto", origin="lower", cmap="inferno",
                     vmin=0, vmax=255, extent=[0, xmax_khz, 0, HIST])
    ax2.set_xlabel("频率 (kHz)")
    ax2.set_ylabel("历史 (越往上越新)")
    fig.colorbar(img, ax=ax2, pad=0.01, fraction=0.04)

    state = {"count": 0}

    def update(_frame):
        got = False
        while True:
            try:
                row = q.get_nowait()
            except queue.Empty:
                break
            wf[:-1] = wf[1:]
            wf[-1, :] = np.frombuffer(row, dtype=np.uint8)
            state["count"] += 1
            got = True
        if got:
            cur = wf[-1, :].astype(np.int32)
            line.set_ydata(cur)
            k = int(np.argmax(cur))
            pktxt.set_text("peak: %.2f kHz (bin %d) | frames=%d"
                           % (k * df_hz / 1000.0, k, state["count"]))
            img.set_data(wf)
        fig.canvas.draw_idle()

    if args.save or args.dump:
        # 自测/诊断模式：先灌 200 帧，再出图 / 出数据文件
        for _ in range(200):
            try:
                wf[:-1] = wf[1:]
                wf[-1, :] = np.frombuffer(q.get(timeout=2.0), dtype=np.uint8)
            except queue.Empty:
                break
        cur = wf[-1, :].astype(np.int32)
        line.set_ydata(cur)
        k = int(np.argmax(cur))
        pktxt.set_text("peak: %.2f kHz (bin %d) | frames=200"
                       % (k * df_hz / 1000.0, k))
        img.set_data(wf)
        if args.save:
            fig.savefig(args.save, dpi=110)
            print("[OK] 自测图已保存:", args.save)
        if args.dump:
            # [10-01] 诊断用：把最后一帧 512 个幅度码写成文本，便于与金标准逐 bin 对账
            with open(args.dump, "w", encoding="utf-8") as f:
                f.write("# 0x8E spectrum frame: 512 bins, code = (b<<4)|frac4 (log-compressed)\n")
                f.write("# f_k = k * 48.828 Hz ; 1kHz SQUARE expected: bins 20/61/102 codes ~209/183/173\n")
                f.write("# min=%d max=%d argmax_bin=%d\n" % (int(cur.min()), int(cur.max()), int(np.argmax(cur))))
                for i, v in enumerate(cur):
                    f.write("%d,%d\n" % (i, int(v)))
            print("[OK] 原始帧已导出:", args.dump)
            top = sorted(range(len(cur)), key=lambda i: -cur[i])[:8]
            print("     最大的几个 bin:", ", ".join("%d(code=%d)" % (i, cur[i]) for i in top))
        stop_evt.set()
        return 0

    from matplotlib.animation import FuncAnimation
    anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    print("运行中（数据源: %s）。关闭窗口即退出。" % src_name)
    try:
        plt.show()
    finally:
        stop_evt.set()
        anim.event_source.stop()
        if isinstance(src, BoardSource):
            print("统计: 有效帧 %d / 校验错 %d / 已请求 %d"
                  % src.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())
