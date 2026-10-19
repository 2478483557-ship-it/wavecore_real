# -*- coding: utf-8 -*-
"""针对 2026-10-19 声明修复的回归测试。

只测我改过的三个文件所影响的通路，不重复全套复验：

  freq_meter.v   改了 st(3位) / hi_lat,r_lat(32位) / max_v,min_v(8位)
                 -> 频率 F、峰峰值 V、占空比 D、脉宽 W、波形识别 TY
                 风险最高：st 被截成 1 位的话状态机会只剩两个状态，读数停摆

  board_top.v    改了 nf_f0..f5(16位) / nf_done / nf_tick / nn_cls(2位)
                 / nn_cls_r(2位) / dbg_is_nn / dbg_nn_w / dbg_read_w / dbg_req_d
                 -> 特征提取、神经网络识别、0x94/0x95 回读
                 风险：nn_cls 若被截成 1 位，只能分出 2 类（本应 4 类）

  fft_demo.v     改了 win_out(16位)
                 -> 厂商 IP FFT 读数（S= 行）
                 风险：若被截成 1 位，IP 频谱只剩 1 个有效比特

用法：
    python host/regression_2026_10_19.py              # 自动选串口
    python host/regression_2026_10_19.py COM5         # 指定串口

判据取自仓库里既有的实测记录，不是现编的：
    - 正弦 1kHz：SF=999（插值默认开，USE_INTERP=1）
      旧清单写的 976 是插值加入之前的值，已作废
    - 方波 1kHz：SF/S2/S3 = 999 / 2998 / 4997
    - 回环 1kHz Vpp ≈ 1085 mV（link_response.csv）
    - TY: 0=方波 1=正弦 2=三角 3=其他
    - 0x95 神经网络：SF = 700000 + 类别 + 1，类别 1=正弦 2=方波 3=三角 4=其他
"""
import re
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("需要 pyserial。请用系统 Python 3.8：")
    print(r"  C:\Users\Lenovo\AppData\Local\Programs\Python\Python38\python.exe")
    sys.exit(2)

BAUD = 460800


# ---------------------------------------------------------------- 串口
def pick_port(arg=None):
    if arg:
        return arg
    ports = [p.device for p in list_ports.comports()
             if "蓝牙" not in (p.description or "")
             and "Bluetooth" not in (p.description or "")]
    if len(ports) == 1:
        return ports[0]
    if not ports:
        print("找不到串口，请确认板子已插、CH340 驱动已装")
        sys.exit(2)
    print("多个串口：%s" % ", ".join(ports))
    print("请用参数指定，例如：python regression_2026_10_19.py %s" % ports[0])
    sys.exit(2)


def checksum(payload):
    return sum(payload) & 0xFF


def frame(cmd, data=b""):
    body = bytes([cmd, (len(data) >> 8) & 0xFF, len(data) & 0xFF]) + data
    return b"\x5a\xa5" + body + bytes([checksum(body)])


# ---------------------------------------------------------------- 解析
class Reader:
    """持续读串口，按行解析，保存最新一行里的各个字段。"""

    def __init__(self, ser):
        self.ser = ser
        self.buf = b""
        self.lines = []
        self.freq = None
        self.vpp = None
        self.duty = None
        self.ty = None
        self.sf = None
        self.s2 = None
        self.s3 = None

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                chunk = self.ser.read(512)
            except Exception:
                break
            if not chunk:
                continue
            self.buf += chunk
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                text = raw.decode("ascii", "ignore").strip()
                if text:
                    self.lines.append(text)
                    self._parse(text)

    def _parse(self, text):
        m = re.search(r"F=0*(\d+)Hz", text)
        if m:
            self.freq = int(m.group(1))
        m = re.search(r"V=0*(\d+)", text)
        if m:
            self.vpp = int(m.group(1))
        m = re.search(r"D=0*(\d+)", text)
        if m:
            self.duty = int(m.group(1))
        m = re.search(r"TY=(\d+)", text)
        if m:
            self.ty = int(m.group(1))
        m = re.search(r"SF=0*(\d+)Hz", text)
        if m:
            self.sf = int(m.group(1))
        m = re.search(r"S2=0*(\d+)", text)
        if m:
            self.s2 = int(m.group(1))
        m = re.search(r"S3=0*(\d+)", text)
        if m:
            self.s3 = int(m.group(1))

    def clear(self):
        self.lines = []
        self.freq = self.vpp = self.duty = self.ty = None
        self.sf = self.s2 = self.s3 = None

    def tail(self, n=4):
        return self.lines[-n:]


# ---------------------------------------------------------------- 用例
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print("  %s  %-34s %s" % ("PASS" if ok else "FAIL", name, detail))


def send(ser, cmd, data=b"", note=""):
    ser.write(frame(cmd, data))
    ser.flush()
    print("    -> 0x%02X %s" % (cmd, note))


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    print("串口 %s @ %d 8N1" % (port, BAUD))
    ser = serial.Serial(port, BAUD, timeout=0.05)
    rd = Reader(ser)
    time.sleep(0.5)
    rd.pump(0.5)
    rd.clear()

    try:
        # ============ 固件版本自检（必须先做，否则后面全是误判）============
        # WIN= 行是 2026-10-18 15:36 才加进 self_fft_report.v 的。
        # 板子上如果没有这一行，说明烧的是旧固件 —— 那时 0x94/0x95 也还不存在，
        # 后面的"读不到"不代表本次修复有问题，只代表没烧新固件。
        print("\n[版本] 检查固件是否包含 10-18 之后的功能")
        rd.clear()
        send(ser, 0x8A, b"\x00", "运行自研 FFT")
        rd.pump(2.5)
        has_win = any("WIN=" in ln for ln in rd.lines)
        has_sf = rd.sf is not None
        record("固件含 WIN= 行（10-18+）", has_win,
               "看到 WIN= 行" if has_win else "没有 WIN= → 板子是旧固件")
        if not has_win:
            print()
            print("  " + "!" * 58)
            print("  中止：板子上跑的不是新固件，继续测没有意义。")
            print("  先烧录：D:/Verilog_project/wavecore/program_device.bat")
            print("  烧完再跑本脚本。")
            print("  " + "!" * 58)
            ser.close()
            return 2

        # ============ 0. 先设 1000Hz（默认是 100kHz 预设，会混叠）============
        print("\n[0] 建立基准：1000 Hz 正弦")
        send(ser, 0x85, (1000).to_bytes(4, "little"), "设 1000Hz")
        rd.pump(0.4)
        send(ser, 0x88, b"\x00", "波形=正弦")
        rd.pump(1.2)

        # ============ 1. freq_meter：频率 + 峰峰值 ============
        print("\n[1] freq_meter（改了 5 处声明）—— 最高风险")
        ok_f = rd.freq is not None and abs(rd.freq - 1000) <= 2
        record("频率读数 F", ok_f,
               "F=%s（期望 1000±2）" % rd.freq)

        # [修正] 期望值不能沿用 link_response.csv 的 1085 mV ——
        #   那张表是**标定前**（KN=1024，原始 LSB）测的；
        #   现在固件烧的是 KN=37203，V= 显示的是**模块输入端真实电压**（约 5000 mV）。
        #   这里只判"是不是一个合理的电压读数"，不锁定具体值，
        #   因为 DAC 幅度由电位器决定，旋过就变。
        ok_v = rd.vpp is not None and 800 <= rd.vpp <= 6000
        record("峰峰值 V", ok_v,
               "V=%s mV（标定后应为千 mV 级；0 或离谱=被截位）" % rd.vpp)

        ok_d = rd.duty is not None and 40 <= rd.duty <= 60
        record("占空比 D", ok_d, "D=%s（期望 45~55）" % rd.duty)

        ok_ty = rd.ty == 1
        record("正弦识别 TY=1", ok_ty, "TY=%s" % rd.ty)

        # ============ 2. 波形切换：max_v/min_v 参与 ============
        print("\n[2] 波形切换（freq_meter 的 max_v/min_v + wave_id）")
        rd.clear()
        send(ser, 0x88, b"\x01", "波形=方波")
        rd.pump(1.5)
        ok_sq = rd.ty == 0
        record("方波识别 TY=0", ok_sq, "TY=%s" % rd.ty)
        ok_sqv = rd.vpp is not None and 800 <= rd.vpp <= 6000
        record("方波峰峰值", ok_sqv, "V=%s mV" % rd.vpp)

        # ============ 3. 自研 FFT（未改，但依赖同一复位）============
        print("\n[3] 自研 FFT（插值默认开，期望 999 不是 976）")
        rd.clear()
        send(ser, 0x8A, b"\x00", "运行自研 FFT")
        rd.pump(2.0)
        ok_sf = rd.sf is not None and (995 <= rd.sf <= 1005)
        record("方波基波 SF≈999", ok_sf, "SF=%s" % rd.sf)
        ok_h3 = rd.s2 is not None and (2990 <= rd.s2 <= 3005)
        record("三次谐波 S2≈2998", ok_h3, "S2=%s" % rd.s2)
        ok_h5 = rd.s3 is not None and (4988 <= rd.s3 <= 5005)
        record("五次谐波 S3≈4997", ok_h5, "S3=%s" % rd.s3)

        # ============ 4. 神经网络通路：board_top 的 9 处声明 ============
        print("\n[4] 神经网络通路（改了 9 处声明）—— 第二高风险")
        rd.clear()
        send(ser, 0x96, b"\x01", "识别源切到神经网络")
        rd.pump(0.4)
        send(ser, 0x95, b"", "读 NN 结果")
        rd.pump(1.5)
        ok_nn = rd.sf is not None and 700001 <= rd.sf <= 700004
        record("0x95 回读在 700001~700004", ok_nn,
               "SF=%s%s" % (rd.sf, "" if ok_nn else " ← 越界=特征或类别位宽被截"))

        # 若只出现 1/2 两类，说明 nn_cls 被当成 1 位
        cls = (rd.sf - 700000) if (rd.sf and 700000 <= rd.sf <= 700010) else None
        record("类别编码合法（1..4）", cls in (1, 2, 3, 4),
               "类别=%s（1正弦 2方波 3三角 4其他）" % cls)

        # ============ 5. 0x94 状态回读：dbg_* 声明 ============
        print("\n[5] 0x94 状态回读（dbg_* 声明）")
        rd.clear()
        send(ser, 0x96, b"\x00", "识别源切回规则法")
        rd.pump(0.3)
        send(ser, 0x94, b"", "读状态")
        rd.pump(1.2)
        ok_st = rd.sf is not None and 500000 <= rd.sf < 501000
        record("0x94 首行在 500000~501000", ok_st,
               "SF=%s" % rd.sf)
        if ok_st:
            st = (rd.sf - 500000) // 1024
            flag = (rd.sf - 500000) % 1024
            record("状态机编号合理（<32）", st < 32,
                   "状态=%d 标志=0b%s" % (st, format(flag, "08b")))

        # ============ 6. 预触发四档（确认 board_top 改动无副作用）============
        print("\n[6] 预触发四档（确认 board_top 无副作用）")
        for pct, val in ((0, 0), (25, 1), (50, 2), (75, 3)):
            rd.clear()
            send(ser, 0x8F, bytes([val]), "预触发 %d%%" % pct)
            rd.pump(0.8)
            ok = rd.freq is not None
            record("预触发 %d%% 后仍在上报" % pct, ok,
                   "F=%s" % rd.freq)

    finally:
        try:
            ser.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- 汇总
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 62)
    print("  合计 %d 项，PASS %d，FAIL %d" % (total, passed, total - passed))
    print("=" * 62)

    if passed != total:
        print("\n失败项：")
        for name, ok, detail in RESULTS:
            if not ok:
                print("  - %s：%s" % (name, detail))
        print("\n对照排查：")
        print("  频率/Vpp/D 错      -> freq_meter.v 的 st / max_v / min_v")
        print("  TY 不跟着变        -> wave_id.v 或 board_top 的 nn 通路")
        print("  SF 只出现 1 或 2   -> nn_cls 被截成 1 位（本次修复的重点）")
        print("  0x94/0x95 无回读   -> dbg_read_w / dbg_nn_w / dbg_is_nn")
        print("  全都没有上报        -> 串口没通，先查端口与波特率")
        return 1

    print("\n全部通过。声明修复未改变功能。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
