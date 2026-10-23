# -*- coding: utf-8 -*-
"""WaveCore FPGA上位机。"""

import csv
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import serial
from serial.tools import list_ports

from matplotlib import rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from protocol import (
    DEFAULT_VPP_KN,
    RAW_LSB_KN,
    StreamParser,
    TIMEBASE_SAMPLE_RATES,
    command_request_spectrum,
    command_request_waveform,
    command_run_self_fft,
    command_set_frequency,
    command_set_preset,
    command_set_pretrigger,
    command_set_second_frequency,
    command_set_sweep,
    command_set_timebase,
    command_set_trigger,
    command_set_vpp_cal,
    command_set_waveform,
    command_set_window,      # [0x90] 窗函数  [10-16]
    command_set_overlap,     # [0x91] 帧重叠  [10-16]
    command_ifft_filter,     # [0x92] IFFT 频域滤波  [10-16]
    command_play_ifft,       # [0x93] IFFT 结果 DAC 回放  [10-16]
    command_read_nn,         # [0x95] 神经网络识别结果  [10-17]
    command_set_ty_source,   # [0x96] 识别来源切换  [10-17]
    command_set_win_auto,    # [0x97] 自适应选窗  [10-18]
    command_set_spec_avg,    # [0x98] 幅度谱平均  [10-18]
)


# [10-23] 波形帧固定 50kHz —— 已与 0x8D 时基解耦（见 src/wave_frame.v）。
#   高频档(T3/T4)下 0x83 返回的仍是 50kHz 采样，时间轴必须按这个值算。
WAVE_SAMPLE_RATE_HZ = 50_000


BAUD_RATE = 460800
RECONNECT_INTERVAL_SECONDS = 1.0
CH340_VID = 0x1A86
CH340_PIDS = {0x7523, 0x5523}

# Matplotlib 默认字体对中文覆盖不完整。按 Windows 常见字体优先级设置后，
# 波形、频谱和导出图中的标题可统一使用中文且不会显示为方框。
rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


def available_ports():
    """返回当前串口列表。"""
    return list(list_ports.comports())


class SerialWorker:
    """后台串口线程，负责收发、解析与自动重连。"""

    def __init__(self):
        self.events = queue.Queue()
        self.outgoing = queue.Queue()
        self.requested_port = None
        self.current_port = None
        self._serial = None
        self._thread = None
        self._stop_event = threading.Event()
        self.timebase_index = 0

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, port_name):
        self.stop()
        # 丢弃上一次连接尚未发出的命令，避免重连后把旧标定值写回FPGA。
        while True:
            try:
                self.outgoing.get_nowait()
            except queue.Empty:
                break
        self.requested_port = port_name
        self.current_port = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

        serial_port = self._serial
        if serial_port is not None:
            try:
                serial_port.close()
            except (serial.SerialException, OSError):
                pass

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

        self._serial = None
        self._thread = None

    def send(self, frame):
        if not self.running:
            raise RuntimeError("串口尚未连接")
        self.outgoing.put(bytes(frame))

    def set_timebase(self, index):
        """同步流解析器使用的采样率档位。"""
        if index not in TIMEBASE_SAMPLE_RATES:
            raise ValueError("时基档位必须是0、1、2或3")
        self.timebase_index = index

    def _find_reconnect_port(self):
        ports = available_ports()

        for port in ports:
            if port.device == self.requested_port:
                return port.device

        ch340_ports = [
            port
            for port in ports
            if port.vid == CH340_VID and port.pid in CH340_PIDS
        ]

        if len(ch340_ports) == 1:
            return ch340_ports[0].device

        return None

    def _close_serial(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
        self._serial = None
        self.current_port = None

    def _run(self):
        parser = StreamParser(TIMEBASE_SAMPLE_RATES[self.timebase_index])
        last_error_message = None

        while not self._stop_event.is_set():
            if self._serial is None:
                port_name = self._find_reconnect_port()

                if port_name is None:
                    message = "未找到选定的CH340串口，正在自动重连"
                    if message != last_error_message:
                        self.events.put({
                            "type": "connection_waiting",
                            "message": message,
                        })
                        last_error_message = message
                    self._stop_event.wait(RECONNECT_INTERVAL_SECONDS)
                    continue

                try:
                    self._serial = serial.Serial(
                        port=port_name,
                        baudrate=BAUD_RATE,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=0.1,
                        write_timeout=1,
                    )
                    self._serial.reset_input_buffer()
                    self.current_port = port_name
                    parser = StreamParser(TIMEBASE_SAMPLE_RATES[self.timebase_index])
                    last_error_message = None
                    self.events.put({
                        "type": "connected",
                        "port": port_name,
                    })
                except (serial.SerialException, OSError) as error:
                    self._close_serial()
                    message = f"连接失败：{error}"
                    if message != last_error_message:
                        self.events.put({
                            "type": "connection_waiting",
                            "message": message,
                        })
                        last_error_message = message
                    self._stop_event.wait(RECONNECT_INTERVAL_SECONDS)
                    continue

            try:
                parser.set_timebase(self.timebase_index)
                while True:
                    try:
                        frame = self.outgoing.get_nowait()
                    except queue.Empty:
                        break
                    self._serial.write(frame)
                    self._serial.flush()

                read_size = max(self._serial.in_waiting, 1)
                data = self._serial.read(read_size)

                for event in parser.feed(data):
                    self.events.put(event)

            except (serial.SerialException, OSError) as error:
                old_port = self.current_port
                self._close_serial()
                self.events.put({
                    "type": "disconnected",
                    "port": old_port,
                    "message": f"串口已断开：{error}",
                })
                self._stop_event.wait(RECONNECT_INTERVAL_SECONDS)

        self._close_serial()


def _fixed_label(parent, var, width, **kwargs):
    """定宽只读标签：内容再长也不会把界面撑宽。

    [10-18] 这是**模块级函数**, 不是类方法 —— 原因:
      tt.Label(width=N) 的单位是"字符数", 内容超长也只是被截断显示,
      不会让父容器重新计算更大的 requested width。
      原来控制面板里的说明文字一变长(勾了自适应), 整个窗口就被撑宽,
      用户看到的是"界面被拉开了"。现在所有会变的文字都走这里。
    """
    return ttk.Label(parent, textvariable=var, width=width, anchor="w", **kwargs)


def _measurement_card(parent, column, title, variable, row=0, width=None):
    """测量卡片。模块级函数（原 @staticmethod 在 Py3.8 类体内不能直接调用）。

    [10-21] 增加 width：识别结果那一格的文字会变长（"1：正弦" ↔
    "3：其他（…超 25kHz…）"），pack 会跟着重排，整行卡片被拉宽再缩回，
    看起来就是"界面一直抖"。给它一个固定字符宽度，文字变化时卡片不动。
    """
    card = ttk.LabelFrame(parent, text=title, padding=(10, 6))
    card.grid(row=row, column=column, sticky="nsew", padx=4, pady=3)
    label = ttk.Label(card, textvariable=variable, style="Value.TLabel")
    if width:
        label.configure(width=width, anchor="w")
    label.pack()
    return card


class WaveCoreApp:
    """WaveCore tkinter主界面。"""

    # [10-21] 波形识别去抖：连续这么多帧一致才更新界面
    TY_STREAK_TO_SHOW = 3

    PRESETS = (
        ("100 kHz", 0, 100_000),
        ("200 kHz", 1, 200_000),
        ("500 kHz", 2, 500_000),
        ("1 MHz", 3, 1_000_000),
    )

    # [2026-10-23] 四档重新开放。T3/T4 不再是 100k/200k，而是**高频频谱档**：
    #   原来那两档在实机上抓不到数据（decim 太小，波形缓存凑不满），
    #   现已改成 6.25MHz / 12.5MHz，只服务频谱。
    #   ⚠️ 波形帧固定 50kHz，不随档位变化（否则高速率下会卡死，见 wave_frame.v）。
    TIMEBASE_CHOICES = (
        ("T1  50 kHz（时域 / 低频）", 0),
        ("T2  12.5 kHz（细分辨率）", 1),
        ("T3  6.25 MHz（高频频谱）", 2),
        ("T4  12.5 MHz（高频频谱）", 3),
    )

    # [v1.21 0x8F] 预触发比例：决定触发点在 1024 点波形帧里的位置
    #   0% 与升级前逐位等价；50% 时触发点落在帧正中央，可以看到触发沿左侧的波形
    # [10-16 v1.22] 窗函数三档: 0=矩形 1=Hann 2=Blackman
    #   副瓣: 矩形 -13dB / Hann -31dB / Blackman -58dB
    #   泄漏只取决于"谱线离 bin 多远": 落在整数 bin 时矩形最优(主瓣最窄、频率精度最高);
    #   落在 bin 正中时泄漏最严重, 此时 Blackman 收益最大。仿真实测(bin100 探针):
    #   矩形 69 / Hann 32 / Blackman 24 (对数码)。
    WINDOW_CHOICES = (
        ("Hann（默认）", 1),
        ("矩形（最窄主瓣）", 0),
        ("Blackman（最强抑漏）", 2),
    )

    PRETRIGGER_CHOICES = (
        ("0%（默认）", 0),
        ("25%", 1),
        ("50%", 2),
        ("75%", 3),
    )
    PRETRIGGER_RATIO = (0.0, 0.25, 0.5, 0.75)

    def __init__(self, root):
        self.root = root
        self.worker = SerialWorker()
        self.connected = False
        self.csv_file = None
        self.csv_writer = None
        self.last_csv_write_time = 0.0
        self.latest_peak_s_hz = None
        self.latest_peak_a_hz = None
        self.latest_duty_percent = None
        self.latest_pulse_width_us = None
        self.latest_waveform_type = None
        # [10-21] TY 去抖状态：连续多少帧一致才显示
        self._ty_pending = None
        self._ty_streak = 0
        self.latest_self_fft_peaks = {"SF": None, "S2": None, "S3": None}
        self.latest_window_used = None
        self.latest_frequency_hz = None
        self.suppress_peak_a_until = 0.0
        # [10-18] 最后一次收到 A 行的时刻。FPGA 只在"存在第二峰"时才发 A 行,
        #   所以超过一段时间没收到 = 第二峰消失了。
        #   这正是 IFFT 滤波成功最直观的表现: 双音 1k+5k -> 滤掉 5k -> A 行不再出现。
        #   原来界面会一直保留旧的 A 值, 看起来像"没变化"。加超时清除后
        #   "两个峰变一个峰"在界面上一眼可见。
        self._last_peak_a_time = 0.0
        self.latest_waveform_samples = None
        self.latest_waveform_sample_rate_hz = None
        self.latest_vpp_value = None
        self.waveform_frame_times = []
        self.auto_waveform_after_id = None
        self.current_timebase_index = 0
        self.current_vpp_kn = DEFAULT_VPP_KN
        self.latest_spectrum_codes = None
        self.spectrum_history = [[0] * 512 for _ in range(120)]
        self.spectrum_frame_count = 0
        self.spectrum_running = False
        self.spectrum_after_id = None
        self.dual_tone_enabled = False
        self.applied_waveform_name = "未设置"
        self.applied_trigger_name = "自由"
        self.sweep_enabled = False

        self.port_var = tk.StringVar()
        self.status_var = tk.StringVar(value="未连接")
        self.frequency_var = tk.StringVar(value="-- Hz")
        self.vpp_var = tk.StringVar(value="-- mV")
        self.peak_s_var = tk.StringVar(value="-- Hz")
        self.peak_a_var = tk.StringVar(value="-- Hz")
        self.duty_var = tk.StringVar(value="-- %")
        self.pulse_width_var = tk.StringVar(value="-- us")
        self.detected_waveform_var = tk.StringVar(value="--")
        # [10-18] 波形识别来源与结果说明
        self.wave_src_info_var = tk.StringVar(
            value="来源：规则法（TY 行随测量自动上报）"
        )
        self.self_fft_var = tk.StringVar(value="-- / -- / -- Hz")
        # [10-18] 当前实际使用的窗 (来自 SF/S2/S3 之后那条 WIN= 行)
        self.win_used_var = tk.StringVar(value="Hann 窗")
        self.main_frequency_var = tk.StringVar(value="1000")
        self.second_frequency_var = tk.StringVar(value="1100")
        self.waveform_choice_var = tk.StringVar(value="正弦")
        self.trigger_choice_var = tk.StringVar(value="自由")
        self.timebase_choice_var = tk.StringVar(value=self.TIMEBASE_CHOICES[0][0])
        self.pretrigger_choice_var = tk.StringVar(value=self.PRETRIGGER_CHOICES[0][0])
        self.pretrigger_info_var = tk.StringVar(
            value="预触发 0%：帧首点 = 触发点（与升级前一致）"
        )
        self.current_pretrigger_index = 0

        # ---- [10-16 v1.22] 新功能状态 ----
        self.window_choice_var = tk.StringVar(value=self.WINDOW_CHOICES[0][0])
        self.window_info_var = tk.StringVar(value="Hann 窗 · 手动")
        self.overlap_var = tk.BooleanVar(value=False)
        self.overlap_info_var = tk.StringVar(value="整帧采集（默认）")
        self.mask_lo_var = tk.StringVar(value="98")
        self.mask_hi_var = tk.StringVar(value="102")
        self.play_var = tk.BooleanVar(value=False)
        self.ifft_info_var = tk.StringVar(value="频域滤波未设置")
        self.timebase_info_var = tk.StringVar()
        self.spectrum_info_var = tk.StringVar(value="尚未请求频谱")
        # [10-17] 实时判据: 底噪(看窗函数) + 帧率(看帧重叠)。都是已有数据算出来的。
        self._spec_last_t = None
        self._spec_fps = 0.0
        self.waveform_info_var = tk.StringVar(value="尚未请求波形")
        self.auto_waveform_var = tk.BooleanVar(value=False)
        self.waveform_interval_var = tk.StringVar(value="2 s")
        self.median_filter_var = tk.BooleanVar(value=False)
        self.applied_settings_var = tk.StringVar()
        # v1.17 电压标定: kn = 每 LSB 多少 mV x1024 (Q10); 8000 = 7.8125 mV/LSB
        self.vpp_kn_var = tk.StringVar(value=str(DEFAULT_VPP_KN))
        self.vpp_cal_info_var = tk.StringVar(
            value=f"当前 KN={DEFAULT_VPP_KN} (7.8125 mV/LSB, 按 0~2V 量程)"
        )
        self._update_timebase_info()
        self._update_applied_settings()

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        # 上电默认是手动 Hann（与 KN_DEF 一样是「已固化的默认」），
        #   统一走一次刷新，避免初始值与后续格式不一致。
        self._refresh_window_info()
        self.refresh_ports()
        self.root.after(50, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self):
        self.root.title("WaveCore FPGA上位机")
        # [10-18] 850 太矮: 串口 64 + 测量 170 + 控制面板 394 之后,
        #   绘图区只剩 186px (22%), 波形和频谱被压成一条。
        #   屏幕 1067 高, 提到 940 仍留出任务栏与标题栏余量。
        self.root.geometry("1200x940")
        # [10-18] 固定初始尺寸, 并且**不自动随内容缩放** ——
        #   原来控制面板里的说明文字会变长(比如勾了自适应), 导致窗口被越撑越宽。
        #   现在: 所有会变的文字都用 _fixed_label 定宽, 窗口尺寸也就稳定了。
        self.root.minsize(1000, 720)

    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 21, "bold"))
        style.configure("CardTitle.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure(
            "Accent.TButton",
            foreground="#0b57d0",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Accent.TButton",
            foreground=[("disabled", "#999999"), ("active", "#0842a0")],
        )
        style.configure("Stop.TButton", foreground="#b3261e")
        style.map(
            "Stop.TButton",
            foreground=[("disabled", "#999999"), ("active", "#8f1d18")],
        )
        style.configure(
            "TLabelframe.Label",
            foreground="#334155",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.configure(
            "TNotebook.Tab",
            padding=(12, 5),
            font=("Microsoft YaHei UI", 9),
        )

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        connection = ttk.LabelFrame(self.root, text="串口连接", padding=(10, 7))
        connection.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="串口：").grid(row=0, column=0, padx=(0, 6))
        self.port_box = ttk.Combobox(
            connection,
            textvariable=self.port_var,
            state="readonly",
            width=36,
        )
        self.port_box.grid(row=0, column=1, sticky="w")
        ttk.Button(connection, text="刷新", command=self.refresh_ports).grid(
            row=0, column=2, padx=6
        )
        self.connect_button = ttk.Button(
            connection,
            text="连接",
            command=self.toggle_connection,
            style="Accent.TButton",
        )
        self.connect_button.grid(row=0, column=3, padx=6)
        ttk.Label(connection, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=4, padx=(12, 0), sticky="e"
        )
        # [10-19] 演示模式按钮：答辩时一键让图表占满屏幕，再按一次回来。
        self.present_button = ttk.Button(
            connection, text="演示模式 F11", width=12,
            command=self._toggle_present_mode
        )
        self.present_button.grid(row=0, column=5, padx=(8, 0))

        measurements = ttk.Frame(self.root, padding=(12, 3))
        measurements.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            measurements.columnconfigure(column, weight=1)

        _measurement_card(measurements, 0, "测量频率 F", self.frequency_var)
        self.vpp_card = _measurement_card(
            measurements, 1, "峰峰值 Vpp (mV)", self.vpp_var
        )
        _measurement_card(measurements, 2, "FFT主峰 S", self.peak_s_var)
        _measurement_card(measurements, 3, "FFT第二峰 A", self.peak_a_var)
        _measurement_card(measurements, 0, "占空比 D", self.duty_var, row=1)
        _measurement_card(measurements, 1, "脉宽 W", self.pulse_width_var, row=1)
        _measurement_card(measurements, 2, "识别结果", self.detected_waveform_var, row=1, width=24)
        _measurement_card(measurements, 3, "自研FFT SF/S2/S3", self.self_fft_var, row=1)

        controls = ttk.LabelFrame(self.root, text="信号与采集控制", padding=(8, 4))
        controls.grid(row=2, column=0, sticky="ew", padx=12, pady=4)

        ttk.Label(controls, text="主频：").grid(row=0, column=0)
        ttk.Entry(controls, textvariable=self.main_frequency_var, width=14).grid(
            row=0, column=1, padx=(0, 4)
        )
        ttk.Label(controls, text="Hz").grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="设置主频", command=self.set_main_frequency).grid(
            row=0, column=3, padx=4
        )

        ttk.Label(controls, text="第二频率：").grid(row=0, column=4, padx=(18, 0))
        ttk.Entry(controls, textvariable=self.second_frequency_var, width=14).grid(
            row=0, column=5, padx=(0, 4)
        )
        ttk.Label(controls, text="Hz").grid(row=0, column=6, padx=(0, 8))
        ttk.Button(
            controls,
            text="开启双音",
            command=self.enable_dual_tone,
            style="Accent.TButton",
        ).grid(
            row=0, column=7, padx=4
        )
        ttk.Button(controls, text="恢复单音", command=self.restore_single_tone).grid(
            row=0, column=8, padx=4
        )

        ttk.Label(controls, text="预设档位：").grid(row=1, column=0, pady=(3, 0))
        for offset, (label, index, frequency) in enumerate(self.PRESETS, start=1):
            ttk.Button(
                controls,
                text=label,
                command=lambda i=index, f=frequency: self.set_preset(i, f),
            ).grid(row=1, column=offset, padx=4, pady=(3, 0))

        self.csv_button = ttk.Button(
            controls,
            text="开始记录CSV",
            command=self.toggle_csv_logging,
            style="Accent.TButton",
        )
        self.csv_button.grid(
            row=1,
            column=5,
            columnspan=2,
            padx=4,
            pady=(3, 0),
            sticky="ew",
        )

        ttk.Button(
            controls,
            text="请求1024点波形",
            command=self.request_waveform,
            style="Accent.TButton",
        ).grid(
            row=1,
            column=7,
            columnspan=2,
            padx=4,
            pady=(3, 0),
            sticky="ew",
        )

        ttk.Label(controls, text="输出波形：").grid(row=2, column=0, pady=(3, 0))
        ttk.Combobox(
            controls,
            textvariable=self.waveform_choice_var,
            values=("正弦", "方波", "三角"),
            state="readonly",
            width=10,
        ).grid(row=2, column=1, padx=4, pady=(3, 0))
        ttk.Button(controls, text="应用波形", command=self.set_waveform_choice).grid(
            row=2, column=2, padx=4, pady=(3, 0)
        )

        ttk.Label(controls, text="触发：").grid(row=2, column=3, pady=(3, 0))
        ttk.Combobox(
            controls,
            textvariable=self.trigger_choice_var,
            values=("自由", "上升沿", "下降沿"),
            state="readonly",
            width=10,
        ).grid(row=2, column=4, padx=4, pady=(3, 0))
        ttk.Button(controls, text="应用触发", command=self.set_trigger_choice).grid(
            row=2, column=5, padx=4, pady=(3, 0)
        )
        ttk.Button(
            controls,
            text="运行自研FFT",
            command=self.run_self_fft,
            style="Accent.TButton",
        ).grid(
            row=2, column=6, padx=4, pady=(3, 0)
        )
        ttk.Button(
            controls,
            text="开始扫频",
            command=lambda: self.set_sweep(True),
            style="Accent.TButton",
        ).grid(
            row=2, column=7, padx=4, pady=(3, 0)
        )
        ttk.Button(
            controls,
            text="停止扫频",
            command=lambda: self.set_sweep(False),
            style="Stop.TButton",
        ).grid(
            row=2, column=8, padx=4, pady=(3, 0)
        )

        # ---- 行3: 电压标定 (v1.17, 0x8C) ----
        # Vpp 现在以 mV 上报。KN = 每 LSB 多少 mV x1024(Q10)。
        # "原始LSB"按钮把 KN 设成 1024, 此时 V 字段就是 ADC 计数 —— 标定第一步用它。
        ttk.Label(controls, text="电压标定 KN：").grid(row=3, column=0, pady=(3, 0))
        ttk.Entry(controls, textvariable=self.vpp_kn_var, width=8).grid(
            row=3, column=1, padx=4, pady=(3, 0)
        )
        ttk.Button(controls, text="应用标定", command=self.apply_vpp_cal).grid(
            row=3, column=2, padx=4, pady=(3, 0)
        )
        ttk.Button(
            controls,
            text="原始LSB模式",
            command=lambda: self.apply_vpp_cal(RAW_LSB_KN),
        ).grid(row=3, column=3, padx=4, pady=(3, 0))
        ttk.Button(
            controls,
            text="恢复默认",
            command=lambda: self.apply_vpp_cal(DEFAULT_VPP_KN),
        ).grid(row=3, column=4, padx=4, pady=(3, 0))
        ttk.Label(controls, textvariable=self.vpp_cal_info_var).grid(
            row=3, column=5, columnspan=4, padx=(12, 0), pady=(3, 0), sticky="w"
        )

        # ---- 行4: 时基档位 (v1.20, 0x8D) ----
        ttk.Label(controls, text="采样时基：").grid(row=4, column=0, pady=(3, 0))
        ttk.Combobox(
            controls,
            textvariable=self.timebase_choice_var,
            values=tuple(label for label, _ in self.TIMEBASE_CHOICES),
            state="readonly",
            width=13,
        ).grid(row=4, column=1, padx=4, pady=(3, 0))
        ttk.Button(controls, text="应用时基", command=self.apply_timebase).grid(
            row=4, column=2, padx=4, pady=(3, 0)
        )
        ttk.Label(controls, textvariable=self.timebase_info_var).grid(
            row=4, column=3, columnspan=6, padx=(12, 0), pady=(3, 0), sticky="w"
        )
        # ---- 行5: 预触发比例 (v1.21, 0x8F) ----
        # 静默命令、无 ACK；只能靠波形图上"触发点的位置"判断是否生效。
        # 0%=帧首点即触发点；50%=触发点位于帧正中（可见触发沿左侧波形）。
        ttk.Label(controls, text="预触发：").grid(row=5, column=0, pady=(3, 0))
        ttk.Combobox(
            controls,
            textvariable=self.pretrigger_choice_var,
            values=tuple(label for label, _ in self.PRETRIGGER_CHOICES),
            state="readonly",
            width=13,
        ).grid(row=5, column=1, padx=4, pady=(3, 0))
        ttk.Button(controls, text="应用预触发", command=self.apply_pretrigger).grid(
            row=5, column=2, padx=4, pady=(3, 0)
        )
        ttk.Label(controls, textvariable=self.pretrigger_info_var).grid(
            row=5, column=3, columnspan=6, padx=(12, 0), pady=(3, 0), sticky="w"
        )

        # ---- 行6: 窗函数 (v1.22, 0x90) ----
        # 静默命令、无 ACK。判据: 看**远离主峰的底噪高度**随窗变化。
        # 副瓣 矩形 -13dB / Hann -31dB / Blackman -58dB -> 底噪依次降低。
        ttk.Label(controls, text="频谱窗：").grid(row=6, column=0, pady=(3, 0))
        ttk.Combobox(
            controls,
            textvariable=self.window_choice_var,
            values=tuple(label for label, _ in self.WINDOW_CHOICES),
            state="readonly",
            width=17,
        ).grid(row=6, column=1, padx=4, pady=(3, 0))
        ttk.Button(controls, text="应用窗函数", command=self.apply_window).grid(
            row=6, column=2, padx=4, pady=(3, 0)
        )
        self.win_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="自适应选窗", variable=self.win_auto_var,
            command=self.apply_win_auto,
        ).grid(row=6, column=4, columnspan=2, padx=(12, 0), pady=(3, 0), sticky="w")
        self.spec_avg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="谱平均(8帧)", variable=self.spec_avg_var,
            command=self.apply_spec_avg,
        ).grid(row=6, column=6, columnspan=2, padx=(12, 0), pady=(3, 0), sticky="w")
        _fixed_label(controls, self.window_info_var, 22).grid(
            row=6, column=3, columnspan=1, padx=(12, 0), pady=(3, 0), sticky="w"
        )

        # ---- 行7: 帧重叠 (v1.22, 0x91) ----
        ttk.Label(controls, text="帧重叠：").grid(row=7, column=0, pady=(3, 0))
        ttk.Checkbutton(
            controls, text="50% 重叠（帧间无空白）", variable=self.overlap_var,
            command=self.apply_overlap,
        ).grid(row=7, column=1, columnspan=2, padx=4, pady=(3, 0), sticky="w")
        _fixed_label(controls, self.overlap_info_var, 40).grid(
            row=7, column=3, columnspan=6, padx=(12, 0), pady=(3, 0), sticky="w"
        )

        # ---- 行8: IFFT 频域滤波 (v1.22, 0x92) + DAC 回放 (0x93) ----
        # 流程: 先按 0x8A 跑一次自研 FFT(产生频谱) -> 设掩膜 -> 运行滤波 -> 开 DAC 回放。
        # 掩膜要给**带宽**, 别只给一根谱线: 加窗把单音展宽成 ±1 bin,
        #   实测只掩 bin100 几乎无压制, 掩 98~102 才到 34 dB。
        ttk.Label(controls, text="频域滤波：").grid(row=8, column=0, pady=(3, 0))
        ttk.Spinbox(
            controls, from_=0, to=511, width=5, textvariable=self.mask_lo_var
        ).grid(row=8, column=1, padx=(4, 16), pady=(3, 0))
        ttk.Label(controls, text="~").grid(row=8, column=1, pady=(3, 0), sticky="e")
        ttk.Spinbox(
            controls, from_=0, to=511, width=5, textvariable=self.mask_hi_var
        ).grid(row=8, column=2, padx=(10, 0), pady=(3, 0))
        ttk.Button(controls, text="运行滤波", command=self.apply_ifft).grid(
            row=8, column=3, padx=4, pady=(3, 0)
        )
        # [10-17 补] 停止频域滤波 / 恢复原始信号。
        #   掩膜是**原地改写** mem 的, 跑过就回不去 —— 只能关回放 + 重采一帧。
        self.ifft_stop_button = ttk.Button(
            controls, text="恢复原始", command=self.stop_ifft
        )
        self.ifft_stop_button.grid(row=8, column=4, padx=4, pady=(3, 0))

        ttk.Checkbutton(
            controls, text="DAC 回放", variable=self.play_var, command=self.toggle_play
        ).grid(row=8, column=5, columnspan=1, padx=4, pady=(3, 0), sticky="w")
        _fixed_label(controls, self.ifft_info_var, 44).grid(
            row=8, column=6, columnspan=4, padx=(12, 0), pady=(3, 0), sticky="w"
        )

        # ===== [10-18] 波形识别：独立一区 =====
        #   原来 NN 的按钮和来源下拉都挤在"频域滤波"那一行（row=8），
        #   跟 IFFT 的功能混在一起，界面上看不出这是"另一种识别方式"。
        #   现在单独一区：左边选来源，右边读结果。
        ttk.Separator(controls, orient="horizontal").grid(
            row=9, column=0, columnspan=10, sticky="ew", pady=(10, 0)
        )
        ttk.Label(controls, text="波形识别：").grid(row=10, column=0, pady=(4, 0))

        self.wave_src_var = tk.StringVar(value="规则法 (TY)")
        self.wave_src_box = ttk.Combobox(
            controls, textvariable=self.wave_src_var,
            values=("规则法 (TY)", "神经网络 (NN)"),
            state="readonly", width=15,
        )
        self.wave_src_box.grid(row=10, column=1, columnspan=2, padx=4, pady=(4, 0), sticky="w")
        self.wave_src_box.bind("<<ComboboxSelected>>", self.on_wave_src_changed)

        _fixed_label(controls, self.wave_src_info_var, 14).grid(
            row=10, column=3, columnspan=2, padx=(12, 0), pady=(4, 0), sticky="w"
        )

        _fixed_label(controls, self.applied_settings_var, 96).grid(
            row=11, column=0, columnspan=10, pady=(3, 0), sticky="w"
        )

        # [10-19 演示模式] 记住上方三行，按 F11 时整行隐藏，绘图区铺满。
        #   赛场投影/答辩时用：控制面板平时要，讲解时挡地方。
        self._present_rows = (connection, measurements, controls)
        self._present_mode = False
        self._saved_geometry = ""
        self.root.bind("<F11>", self._toggle_present_mode)
        self.root.bind("<Escape>", self._exit_present_mode)

        self.plot_notebook = ttk.Notebook(self.root)
        self.plot_notebook.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 10))
        # [10-18] 绘图区保底高度。控制面板一旦再加行, 这里也不会被压到看不见;
        #   超出时窗口会被撑高, 而不是牺牲曲线。
        self.plot_notebook.configure(height=520)

        waveform_tab = ttk.Frame(self.plot_notebook)
        self.spectrum_tab = ttk.Frame(self.plot_notebook)
        self.plot_notebook.add(waveform_tab, text="波形")
        self.plot_notebook.add(self.spectrum_tab, text="频谱 / 瀑布")
        waveform_tab.columnconfigure(0, weight=1)
        waveform_tab.rowconfigure(0, weight=1)
        self.spectrum_tab.columnconfigure(0, weight=1)
        self.spectrum_tab.rowconfigure(1, weight=1)

        self.waveform_frame = ttk.LabelFrame(
            waveform_tab,
            text="波形（T1，50 kHz采样）",
            padding=8,
        )
        self.waveform_frame.grid(row=0, column=0, sticky="nsew")
        self.waveform_frame.columnconfigure(0, weight=1)
        self.waveform_frame.rowconfigure(0, weight=1)

        # 约束布局会随窗口尺寸动态为坐标标题和刻度留白，避免横轴标题被
        # 下方状态栏裁掉；这与频谱/瀑布页使用相同的自适应布局策略。
        self.figure = Figure(figsize=(8, 4), dpi=100, constrained_layout=True)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_xlabel("时间（ms）")
        self.axis.set_ylabel("ADC码值（LSB）")
        self.axis.set_xlim(0, 20.48)
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)

        self.canvas = FigureCanvasTkAgg(self.figure, master=self.waveform_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        waveform_actions = ttk.Frame(self.waveform_frame)
        waveform_actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        waveform_actions.columnconfigure(0, weight=1)
        ttk.Label(
            waveform_actions,
            textvariable=self.waveform_info_var,
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            waveform_actions,
            text="显示5点中值滤波",
            variable=self.median_filter_var,
            command=self._on_waveform_filter_changed,
        ).grid(row=1, column=0, padx=(0, 8), pady=(4, 0), sticky="w")
        ttk.Checkbutton(
            waveform_actions,
            text="自动刷新",
            variable=self.auto_waveform_var,
            command=self.toggle_auto_waveform,
        ).grid(row=1, column=1, padx=(8, 4), pady=(4, 0))
        ttk.Combobox(
            waveform_actions,
            textvariable=self.waveform_interval_var,
            values=("500 ms", "1 s", "2 s"),
            state="readonly",
            width=7,
        ).grid(row=1, column=2, padx=4, pady=(4, 0))
        self.export_wave_button = ttk.Button(
            waveform_actions,
            text="导出当前波形CSV",
            command=self.export_waveform_csv,
            state="disabled",
        )
        self.export_wave_button.grid(
            row=1,
            column=3,
            padx=(8, 0),
            pady=(4, 0),
            sticky="e",
        )

        spectrum_actions = ttk.Frame(self.spectrum_tab, padding=(8, 6))
        spectrum_actions.grid(row=0, column=0, sticky="ew")
        spectrum_actions.columnconfigure(2, weight=1)
        self.spectrum_start_button = ttk.Button(
            spectrum_actions,
            text="开始实时频谱",
            command=self.start_spectrum,
            style="Accent.TButton",
        )
        self.spectrum_start_button.grid(row=0, column=0, padx=(0, 6))
        self.spectrum_stop_button = ttk.Button(
            spectrum_actions,
            text="停止频谱",
            command=self.stop_spectrum,
            state="disabled",
            style="Stop.TButton",
        )
        self.spectrum_stop_button.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(spectrum_actions, textvariable=self.spectrum_info_var).grid(
            row=0, column=2, sticky="w"
        )
        self.export_spectrum_button = ttk.Button(
            spectrum_actions,
            text="导出当前频谱CSV",
            command=self.export_spectrum_csv,
            state="disabled",
        )
        self.export_spectrum_button.grid(row=0, column=3, padx=(8, 0), sticky="e")

        # 两幅图共享频率轴，只有最下方显示横轴刻度。约束布局会为轴标签和
        # 颜色条自动留白，避免窗口高度较小时出现裁切、纵轴标题重叠。
        self.spectrum_figure = Figure(
            figsize=(8, 5),
            dpi=100,
            constrained_layout=True,
        )
        spectrum_grid = self.spectrum_figure.add_gridspec(
            2,
            1,
            height_ratios=(1.0, 1.2),
            hspace=0.02,
        )
        self.spectrum_axis = self.spectrum_figure.add_subplot(spectrum_grid[0])
        self.waterfall_axis = self.spectrum_figure.add_subplot(
            spectrum_grid[1],
            sharex=self.spectrum_axis,
        )
        fs_hz = TIMEBASE_SAMPLE_RATES[self.current_timebase_index]
        frequency_khz = [index * fs_hz / 1024.0 / 1000.0 for index in range(512)]
        self.spectrum_line, = self.spectrum_axis.plot(
            frequency_khz,
            [0] * 512,
            linewidth=1.1,
            color="#1769aa",
        )
        self.spectrum_axis.set_xlim(0, fs_hz / 2000.0)
        self.spectrum_axis.set_ylim(0, 255)
        # 子图高度可能很小，外侧旋转的两个ylabel会在交界处相撞。
        # 改为图内角标后，无论窗口高度如何都不会互相覆盖。
        self.spectrum_axis.set_ylabel("")
        self.spectrum_axis.tick_params(axis="x", bottom=False, labelbottom=False)
        self.spectrum_axis.tick_params(axis="both", labelsize=8)
        self.spectrum_axis.set_yticks((0, 128, 255))
        self.spectrum_axis.spines["bottom"].set_visible(False)
        self.spectrum_axis.grid(alpha=0.3)
        self.spectrum_axis.text(
            0.006,
            0.90,
            "幅度",
            transform=self.spectrum_axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="#333333",
            bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "pad": 1.5},
        )
        self.spectrum_peak_text = self.spectrum_axis.text(
            0.99,
            0.94,
            "",
            ha="right",
            va="top",
            fontsize=8,
            transform=self.spectrum_axis.transAxes,
        )
        self.waterfall_image = self.waterfall_axis.imshow(
            self.spectrum_history,
            aspect="auto",
            origin="lower",
            cmap="inferno",
            vmin=0,
            vmax=255,
            extent=[0, fs_hz / 2000.0, 0, len(self.spectrum_history)],
        )
        self.waterfall_axis.set_xlabel("频率（kHz）")
        self.waterfall_axis.set_ylabel("")
        self.waterfall_axis.tick_params(axis="x", top=False, labelsize=8)
        self.waterfall_axis.tick_params(axis="y", labelsize=8)
        self.waterfall_axis.set_yticks((0, 60, 120))
        self.waterfall_axis.spines["top"].set_visible(False)
        self.waterfall_axis.text(
            0.006,
            0.90,
            "历史",
            transform=self.waterfall_axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="white",
            bbox={"facecolor": "black", "alpha": 0.45, "edgecolor": "none", "pad": 1.5},
        )
        self.spectrum_colorbar = self.spectrum_figure.colorbar(
            self.waterfall_image,
            ax=self.waterfall_axis,
            pad=0.01,
            fraction=0.035,
        )
        self.spectrum_colorbar.set_label("幅度码值", labelpad=4)
        self.spectrum_colorbar.ax.tick_params(labelsize=8)
        self.spectrum_canvas = FigureCanvasTkAgg(
            self.spectrum_figure,
            master=self.spectrum_tab,
        )
        self.spectrum_canvas.get_tk_widget().grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=8,
            pady=(0, 8),
        )
    def refresh_ports(self):
        ports = available_ports()
        devices = [port.device for port in ports]
        self.port_box["values"] = devices

        current = self.port_var.get()
        if current not in devices:
            ch340 = [
                port.device
                for port in ports
                if port.vid == CH340_VID and port.pid in CH340_PIDS
            ]
            if ch340:
                self.port_var.set(ch340[0])
            elif devices:
                self.port_var.set(devices[0])
            else:
                self.port_var.set("")

    def toggle_connection(self):
        if self.worker.running:
            self.worker.stop()
            self.connected = False
            self.status_var.set("已断开")
            self.connect_button.configure(text="连接", style="Accent.TButton")
            return

        port_name = self.port_var.get().strip()
        if not port_name:
            messagebox.showwarning("未选择串口", "请先刷新并选择串口")
            return

        self.status_var.set("正在连接……")
        self.connect_button.configure(text="断开", style="Stop.TButton")
        self.worker.start(port_name)

    def _send(self, frame, description):
        if not self.connected:
            messagebox.showwarning("串口未连接", "请先连接FPGA串口")
            return False

        try:
            self.worker.send(frame)
            self.status_var.set(description)
            return True
        except RuntimeError as error:
            messagebox.showerror("发送失败", str(error))
            return False

    @staticmethod
    def _parse_frequency(value, field_name):
        try:
            frequency = int(value.strip())
        except ValueError as error:
            raise ValueError(f"{field_name}必须是数字整数") from error

        if not 1 <= frequency <= 12_500_000:
            raise ValueError(f"{field_name}必须在1～12500000 Hz之间")
        return frequency

    def set_main_frequency(self):
        try:
            frequency = self._parse_frequency(self.main_frequency_var.get(), "主频")
            frame = command_set_frequency(frequency)
        except ValueError as error:
            messagebox.showerror("频率错误", str(error))
            return

        if self._send(frame, f"已发送主频 {frequency} Hz"):
            self.dual_tone_enabled = False
            self.latest_peak_a_hz = None
            self.peak_a_var.set("-- Hz")
            self._last_peak_a_time = 0.0
            self.suppress_peak_a_until = time.monotonic() + 1.0
            self._invalidate_self_fft()
            self._update_applied_settings()

    def enable_dual_tone(self):
        try:
            frequency = self._parse_frequency(
                self.second_frequency_var.get(),
                "第二频率",
            )
            frame = command_set_second_frequency(frequency)
        except ValueError as error:
            messagebox.showerror("频率错误", str(error))
            return

        if self._send(frame, f"已开启第二频率 {frequency} Hz"):
            self.dual_tone_enabled = True
            self.suppress_peak_a_until = 0.0
            self.latest_duty_percent = None
            self.latest_pulse_width_us = None
            self.duty_var.set("--（双音）")
            self.pulse_width_var.set("--（双音）")
            self._invalidate_self_fft()
            self._update_applied_settings()

    def restore_single_tone(self):
        self.set_main_frequency()

    def set_preset(self, index, frequency):
        frame = command_set_preset(index)
        if self._send(frame, f"已发送预设档位 {frequency} Hz"):
            self.dual_tone_enabled = False
            self.main_frequency_var.set(str(frequency))
            self.latest_peak_a_hz = None
            self.peak_a_var.set("-- Hz")
            self.suppress_peak_a_until = time.monotonic() + 1.0
            self._invalidate_self_fft()
            self._update_applied_settings()

    def request_waveform(self):
        self._send(command_request_waveform(), "已请求波形，等待1024点数据")

    def toggle_auto_waveform(self):
        if self.auto_waveform_var.get():
            self.waveform_frame_times.clear()
            self._request_auto_waveform()
        else:
            self._stop_auto_waveform()

    def _waveform_interval_ms(self):
        intervals = {
            "500 ms": 500,
            "1 s": 1000,
            "2 s": 2000,
        }
        return intervals.get(self.waveform_interval_var.get(), 2000)

    def _request_auto_waveform(self):
        self.auto_waveform_after_id = None
        if not self.auto_waveform_var.get():
            return

        if self.connected:
            try:
                self.worker.send(command_request_waveform())
            except RuntimeError:
                pass

        self.auto_waveform_after_id = self.root.after(
            self._waveform_interval_ms(),
            self._request_auto_waveform,
        )

    def _stop_auto_waveform(self):
        if self.auto_waveform_after_id is not None:
            self.root.after_cancel(self.auto_waveform_after_id)
            self.auto_waveform_after_id = None

    def start_spectrum(self):
        if self.spectrum_running:
            return
        if not self._send(command_request_spectrum(), "已开始请求实时频谱"):
            return

        self.spectrum_running = True
        self.spectrum_start_button.configure(state="disabled")
        self.spectrum_stop_button.configure(state="normal")
        self.spectrum_info_var.set("正在等待512点幅度谱……")
        self.plot_notebook.select(self.spectrum_tab)
        self._schedule_spectrum_request()

    def stop_spectrum(self):
        self.spectrum_running = False
        if self.spectrum_after_id is not None:
            self.root.after_cancel(self.spectrum_after_id)
            self.spectrum_after_id = None
        self.spectrum_start_button.configure(state="normal")
        self.spectrum_stop_button.configure(state="disabled")
        if self.latest_spectrum_codes is None:
            self.spectrum_info_var.set("实时频谱已停止，尚未收到有效谱帧")
        else:
            self.spectrum_info_var.set(
                f"实时频谱已停止，共收到{self.spectrum_frame_count}帧"
            )
        # [10-17] 停频谱时清掉帧率, 免得下次显示陈旧值
        self._spec_last_t = None
        self._spec_fps = 0.0

    def _schedule_spectrum_request(self):
        if not self.spectrum_running:
            return
        self.spectrum_after_id = self.root.after(
            150,
            self._request_next_spectrum,
        )

    def _request_next_spectrum(self):
        self.spectrum_after_id = None
        if not self.spectrum_running:
            return
        if self.connected:
            try:
                self.worker.send(command_request_spectrum())
            except RuntimeError:
                pass
        self._schedule_spectrum_request()

    def set_waveform_choice(self):
        choices = {"正弦": 0, "方波": 1, "三角": 2}
        name = self.waveform_choice_var.get()
        waveform_type = choices.get(name)
        if waveform_type is None:
            messagebox.showerror("波形错误", "请选择正弦、方波或三角")
            return
        if self._send(command_set_waveform(waveform_type), f"已切换输出波形：{name}"):
            self.applied_waveform_name = name
            # 波形切换后旧第二峰已不再代表当前信号，在这里清空一次即可。
            # 不在每个S主峰报文到达时清空，避免S与A分开发送期间CSV偶发空值。
            self.latest_peak_a_hz = None
            self.peak_a_var.set("-- Hz")
            self._invalidate_self_fft()
            self._update_applied_settings()

    def _refresh_pretrigger_hint(self):
        """刷新预触发说明。

        [10-21] 实测发现：**自由模式下预触发不起作用**。
          实测上升沿位置：自由模式 504/491/535/529（散布 ±20 点）；
                        上升沿模式 513/513/513（完全固定）。
        这是合理的 —— 没有触发点就无从谈起"触发之前"。
        但界面上原来只是照常显示档位，用户会以为"预触发不准"。
        """
        index = self.current_pretrigger_index
        label = self.PRETRIGGER_CHOICES[index][0]
        ratio = self.PRETRIGGER_RATIO[index]

        if self.applied_trigger_name == "自由":
            self.pretrigger_info_var.set(
                f"预触发 {label}：自由模式没有触发点，此设置不生效 —— "
                "先选『上升沿』或『下降沿』"
            )
            return

        if index == 0:
            self.pretrigger_info_var.set("预触发 0%：帧首点 = 触发点（与升级前一致）")
        else:
            self.pretrigger_info_var.set(
                f"预触发 {label}：触发点位于帧内第 {int(1024 * ratio)} 点，"
                f"可见触发沿左侧的波形"
            )

    def set_trigger_choice(self):
        choices = {"自由": 0, "上升沿": 1, "下降沿": 2}
        name = self.trigger_choice_var.get()
        trigger_mode = choices.get(name)
        if trigger_mode is None:
            messagebox.showerror("触发错误", "请选择自由、上升沿或下降沿")
            return
        if self._send(command_set_trigger(trigger_mode), f"已设置触发模式：{name}"):
            self.applied_trigger_name = name
            self._refresh_pretrigger_hint()
            self._update_applied_settings()
            if self.latest_waveform_samples and self.latest_waveform_sample_rate_hz:
                self._draw_waveform(
                    self.latest_waveform_samples,
                    self.latest_waveform_sample_rate_hz,
                )

    def run_self_fft(self):
        if self._send(command_run_self_fft(), "已请求运行一次自研FFT"):
            self.latest_self_fft_peaks = {"SF": None, "S2": None, "S3": None}
            self.self_fft_var.set("等待结果……")

    def _invalidate_self_fft(self):
        """信号或FFT时基改变后，旧SF/S2/S3不再代表当前输入。"""
        self.latest_self_fft_peaks = {"SF": None, "S2": None, "S3": None}
        self.self_fft_var.set("-- / -- / -- Hz")

    def set_sweep(self, enabled):
        action = "开始" if enabled else "停止"
        if self._send(command_set_sweep(enabled), f"已发送{action}扫频命令"):
            self.sweep_enabled = enabled
            self._invalidate_self_fft()
            self._update_applied_settings()

    def _update_applied_settings(self):
        tone_text = "双音" if self.dual_tone_enabled else "单音"
        sweep_text = "扫频中" if self.sweep_enabled else "扫频关闭"
        self.applied_settings_var.set(
            "控制状态（按最近成功发送）："
            f"波形 {self.applied_waveform_name}｜"
            f"触发 {self.applied_trigger_name}｜"
            f"时基 T{self.current_timebase_index + 1}｜"
            f"预触发 {self.PRETRIGGER_CHOICES[self.current_pretrigger_index][0]}｜"
            f"{sweep_text}｜{tone_text}"
        )

    def _selected_timebase_index(self):
        choices = dict(self.TIMEBASE_CHOICES)
        try:
            return choices[self.timebase_choice_var.get()]
        except KeyError as error:
            # [2026-10-14] 选项由 TIMEBASE_CHOICES 决定（当前只开放 T1/T2），
            #   这里动态列出，避免以后恢复档位时提示文字忘了同步。
            raise ValueError(
                "请选择 %s 时基" % "、".join(label for label, _ in self.TIMEBASE_CHOICES)
            ) from error

    @staticmethod
    def _fmt_hz(hz):
        """频率按量级显示：小于 1MHz 用 kHz，否则用 MHz。

        [10-23] 原来一律除 1000 当 kHz 显示，到了 12.5MHz 会写成
        「12500 kHz」，既不好读也容易看错量级。
        """
        if hz >= 1_000_000:
            return f"{hz / 1_000_000:g} MHz"
        return f"{hz / 1000:g} kHz"

    def _update_timebase_info(self):
        idx = self.current_timebase_index
        fs_hz = TIMEBASE_SAMPLE_RATES[idx]
        resolution_hz = fs_hz / 1024.0
        span_hz = fs_hz / 2.0
        line = (
            f"当前T{idx + 1}：fs={self._fmt_hz(fs_hz)}，"
            f"Δf={resolution_hz:.1f} Hz，"
            f"频谱范围 0～{self._fmt_hz(span_hz)}"
        )
        if idx >= 2:
            line += "　（高频档，仅频谱）"
        self.timebase_info_var.set(line)
        if hasattr(self, "waveform_frame"):
            # 波形通路已与时基解耦，固定 50kHz —— 不能再写成"当前档位采样"
            self.waveform_frame.configure(text="波形（固定 50 kHz 采样）")

    def _selected_pretrigger_index(self):
        choices = dict(self.PRETRIGGER_CHOICES)
        try:
            return choices[self.pretrigger_choice_var.get()]
        except KeyError as error:
            raise ValueError("请选择0%、25%、50%或75%预触发") from error

    # ===================== [10-16 v1.22] 新增功能 =====================
    def _toggle_present_mode(self, event=None):
        """F11：进入/退出演示模式。

        进入时把串口行、测量卡片、控制面板整行隐藏（grid_remove 会记住位置，
        退出时 grid() 原地复原，不需要重算布局），并把窗口切全屏。
        绘图区本来就占 row=3 的权重 1，上面三行一没，它就自动铺满。

        为什么不做"另开一个串口的大窗口"：
          Windows 下 pyserial 是独占打开（源码 serialwin32.py 的 CreateFile
          共享参数为 0），一个 COM 口只能被一个进程持有；而且板子第二个串口
          uart_stm32_txd 是主串口的原样镜像，接出来也是同一份字节流。
          所以放大只能靠布局，不能靠加通道。
        """
        if self._present_mode:
            self._exit_present_mode()
            return

        self._saved_geometry = self.root.geometry()
        for widget in self._present_rows:
            widget.grid_remove()
        self.plot_notebook.grid_configure(padx=0, pady=0)
        self.root.attributes("-fullscreen", True)
        self._present_mode = True
        if hasattr(self, "present_button"):
            self.present_button.configure(text="退出演示 Esc")
        self.status_var.set("演示模式：F11 或 Esc 退出")

    def _exit_present_mode(self, event=None):
        """Esc / 再按 F11：恢复三行面板与窗口尺寸。"""
        if not self._present_mode:
            return
        self.root.attributes("-fullscreen", False)
        self.plot_notebook.grid_configure(padx=12, pady=(4, 10))
        for widget in self._present_rows:
            widget.grid()
        if self._saved_geometry:
            self.root.geometry(self._saved_geometry)
        self._present_mode = False
        if hasattr(self, "present_button"):
            self.present_button.configure(text="演示模式 F11")

    def _refresh_window_info(self):
        """把"当前实际用的窗"和"手动/自适应"合并成一行小字。

        [10-18 二次修改] 起初给「当前窗」单独做了一张卡片，占了测量区一整行，
        把下面的波形图和频谱图压掉一大截 —— 用户反馈"压得太多了"。
        窗名本来就和"自适应/手动"是同一件事的两个侧面，合成一行更好：
            矩形窗 · 自适应      Hann 窗 · 手动
        既不新增控件，也不占额外高度。
        """
        name = self.win_used_var.get()
        mode = "自适应" if self.win_auto_var.get() else "手动"
        self.window_info_var.set("%s · %s" % (name, mode))

    def apply_window(self):
        """发送 0x90 窗函数档位。

        静默命令、无 ACK。判据: 看频谱上**远离主峰的底噪高度** ——
        矩形最高 / Hann 次之 / Blackman 最低(副瓣 -13/-31/-58 dB)。
        """
        index = dict((label, val) for label, val in self.WINDOW_CHOICES)[
            self.window_choice_var.get()
        ]
        if not self._send(command_set_window(index), "已发送窗函数命令"):
            return
        detail = {
            0: "矩形：主瓣最窄、频率精度最高，但泄漏最大（-13 dB）",
            1: "Hann：折中档（-31 dB），也是上电默认",
            2: "Blackman：抑漏最强（-58 dB），主瓣最宽",
        }[index]
        # [10-18] 自适应关着的时候, 手动选的就是实际在用的 -> 立刻更新卡片,
        #   不用等下一次 FFT 回传 WIN= 行。
        if not self.win_auto_var.get():
            self.win_used_var.set(
                {0: "矩形窗", 1: "Hann 窗", 2: "Blackman 窗"}[index]
            )
        self._refresh_window_info()
        # detail 里是"矩形 -13dB / Hann -31dB / Blackman -58dB"这类解释，
        #   放在状态栏一次即可，不长期占据控制面板那一行。
        self.status_var.set(detail)
        self._refresh_window_info()

    def apply_overlap(self):
        """发送 0x91 帧重叠开关。

        on 时每帧只采 512 个新点、前半复用上一帧后半 -> 帧间无空白，
        且采集时间减半（DECIM=1000 时刷新率约翻倍）。
        """
        on = bool(self.overlap_var.get())
        if not self._send(command_set_overlap(on), "已发送帧重叠命令"):
            return
        self.overlap_info_var.set(
            "50% 重叠：帧间无信号空白、刷新率约翻倍" if on else "整帧采集（默认，与升级前一致）"
        )

    def apply_spec_avg(self):
        """开关幅度谱 8 帧平均（0x98）。

        对 0x8E 谱帧做线性域 8 帧滑动平均，底噪降 sqrt(8) 约 4.5dB。
        代价：时间常数约 8 帧（T1 下约 160ms），快变细节会被平滑。
        """
        on = self.spec_avg_var.get()
        if not self._send(command_set_spec_avg(on), "已切换谱平均"):
            return
        self.ifft_info_var.set(
            "谱平均：%s（底噪%s）" % ("8 帧" if on else "关", "降约 4.5dB" if on else "按单帧")
        )

    def apply_win_auto(self):
        """开关自适应选窗（0x97）。

        硬件看主峰偏离整数 bin 的程度 |delta| 自己选窗：
          |delta| < 0.15 bin -> 矩形（主瓣最窄、峰唯一）
          |delta| >= 0.15 bin -> Hann（压泄漏）
        delta 就是插值本来就在算的量，不额外增加运算。

        ★ 看不出区别是正常的：
          |delta| 在 0~0.5 bin 均匀分布，阈值 0.15 意味着约 70% 的情况选 Hann，
          而 Hann 本来就是手动默认档 —— 所以大多数频率下"开了等于没开"。
          想看它真的切换，把频率设成**整 bin**的：976 / 1953 / 4883 Hz
          （整 bin = k x 48.828 Hz）。此时会选矩形，频谱从"3 根等高线"
          变成"1 根高线 + 很矮的肩"。
          想看它当前选了哪个窗：发 0x94，SF-500000 的 bit6（64）= 选了 Hann。
        """
        auto = self.win_auto_var.get()
        if not self._send(command_set_win_auto(auto), "已切换选窗方式"):
            return
        # [10-18] 只给短状态。原来那段"多数频率下判为 Hann…试 976Hz…"太长,
        #   一勾选就把整行撑宽、整个窗口被拉大。说明写在文档里, 这里只留 4 个字。
        if auto:
            # 自适应下实际用哪个窗, 要等硬件判完才知道 —— 靠回传的 WIN= 行更新。
            self.win_used_var.set("待判定")
            # [10-21 修复] **必须主动跑一次 FFT**。
            #   原来只把文字设成"待判定"就不管了：WIN= 行只在自研 FFT 跑完时
            #   由硬件补发，用户不手动点「运行自研 FFT」，这一行永远是"待判定"。
            #   切换识别来源那边早就踩过同一个坑（见 on_wave_src_changed），
            #   这里漏了同样的处理。
            self._send(command_run_self_fft(), "自适应已开，正在判定用哪个窗")
        self._refresh_window_info()

    def on_wave_src_changed(self, event=None):
        """下拉框一改就切换识别来源（0x96），并立刻要一帧结果。

        两条通路（规则法 / 神经网络）**始终在跑**，0x96 只决定
        `TY=` 行上报哪一路。默认规则法，与升级前完全一致。

        ★ 切换后必须**主动请求一帧**（0x83 波形请求同时带测量行）。
          否则 TY 行要等下一次请求才刷新，界面上看着像"切了没反应" ——
          这一点是用户实测反馈后才发现的。
        """
        use_nn = self.wave_src_var.get().startswith("神经网络")
        if not self._send(command_set_ty_source(use_nn),
                          "已切换到%s" % ("神经网络" if use_nn else "规则法")):
            return
        # 立刻要一帧，让 TY 行按新来源刷新
        self._send(command_request_waveform(), "已切换识别来源，正在刷新一帧")
        # [10-18] 同上, 只给短状态, 避免撑宽界面
        self.wave_src_info_var.set("神经网络" if use_nn else "规则法")

    def stop_ifft(self):
        """停止频域滤波，把信号恢复成未滤波状态。

        为什么要单独一个按钮：掩膜是**原地改写**存储器的。0x92 跑完后
        mem 里已经是"滤掉某频段"的时域结果，没法靠再发一条命令撤销。
        唯一的恢复办法是：
          ① 关回放(0x93=0) —— DDS 重新驱动 DAC，回放态也让出 FSM；
          ② 重跑一次正向 FFT(0x8A) —— 重新采集，mem 换回原始数据。

        副作用（要告诉用户）：重采集会重新取样，波形相位会变。
        """
        if self.play_var.get():
            self.play_var.set(False)
            if not self._send(command_play_ifft(False), "已关闭回放"):
                return
        if not self._send(command_run_self_fft(), "已重新采集（恢复原始频谱）"):
            return
        self.ifft_info_var.set(
            "频域滤波已停止：回放关闭、重新采集原始数据（相位会变）"
        )

    def apply_ifft(self):
        """一键完成频域滤波：0x8A 跑正向 FFT -> 等它跑完 -> 0x92 掩膜 + 反向变换。

        ★ 为什么必须三步
          - 0x8A 之后 mem 里是**频谱**
          - 0x92 之后 mem 里才是**时域波形**
          - 0x93 回放读的是 mem
        少了 0x92 就开回放，等于把频域数据当场放出来 —— 示波器上就是"一堆毛刺"。
        原来这里只发 0x92，没先跑 0x8A，是演示失败的直接原因。

        掩膜要给带宽，不要只给一根谱线（加窗会展宽 ±2 bin）。
        """
        try:
            lo = int(self.mask_lo_var.get())
            hi = int(self.mask_hi_var.get())
            frame = command_ifft_filter(lo, hi)
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("频域滤波参数错误", str(error))
            return
        if not self.connected:
            messagebox.showwarning("串口未连接", "请先连接FPGA串口")
            return
        if lo >= hi:
            messagebox.showerror("掩膜范围错误", "起始 bin 必须小于结束 bin")
            return

        # 第 0 步：**必须停掉实时频谱**。
        #   频谱页每 150ms 发一次 0x8E，每次都会**重新采集**一帧 ——
        #   它会把 mem 反复冲掉，导致反向变换的成果活不过 150ms，
        #   表现出来就是"DAC 回放什么都没有"（play_valid 刚置 1 就被清 0）。
        #   这是整个 IFFT 演示最隐蔽的坑。
        if self.spectrum_running:
            self.stop_spectrum()
            warn_msg = "（已自动停止实时频谱：它会每 150ms 重采一帧，冲掉回放数据）"
        else:
            warn_msg = ""

        # 第 1 步：跑一次正向 FFT（采集 + 蝶形 + 找峰），让 mem 里有一帧频谱
        if not self._send(command_run_self_fft(), "第 1/3 步：采集并跑正向 FFT…"):
            return
        self.ifft_info_var.set("1/3 正向 FFT 运行中…（约 0.3 秒）" + warn_msg)

        # 第 2 步：等 FFT 跑完再发 0x92。
        #   0x8A 需要采 1024 点 + 10 级蝶形，T1 时约 20ms 采集；
        #   留 400ms 余量，避免 0x92 早到（那时 mem 还没写完，反向会跑在旧数据上）。
        def _step2():
            self._send(frame, "第 2/3 步：掩膜 bin %d~%d 并反向变换…" % (lo, hi))
            self.ifft_info_var.set(
                "2/3 反向变换中…（约 0.3 秒）"
            )
            self.root.after(400, _step3)

        # 第 3 步：提示下一步
        def _step3():
            self.ifft_info_var.set(
                "3/3 完成 → 勾选「DAC 回放」；示波器接 DA 输出（探头×1，2V/格）"
            )

        self.root.after(400, _step2)

    def toggle_play(self):
        """发送 0x93：把 IFFT 的时域结果循环送 DAC。

        开启时 DDS 让出 DAC；关闭即恢复 DDS 驱动。
        注意：往返衰减 1/N，输出幅度只有约 1/5 满量程（硬件内已做 5 倍增益与饱和）。
        """
        on = bool(self.play_var.get())
        # 开回放前必须停掉实时频谱：它每 150ms 重采一帧，会把 mem 冲掉，
        # 回放会变成静音（play_valid 被反复清零）或毛刺（mem 里是频谱）。
        stopped_spec = False
        if on and self.spectrum_running:
            self.stop_spectrum()
            stopped_spec = True
        if not self._send(command_play_ifft(on), "已发送回放命令"):
            return
        if on:
            msg = "DAC 回放中：示波器接 DA 输出可见滤波后波形"
            if stopped_spec:
                msg += "（已自动停止实时频谱）"
        else:
            msg = "已停止回放，DDS 重新驱动 DAC"
        self.ifft_info_var.set(msg)

    def apply_pretrigger(self):
        """发送 0x8F 预触发比例（v1.21）。

        静默命令：没有 ACK，只能靠波形图上触发点的位置判断是否生效。
        与 0x89 配合：先选触发模式，再选预触发档，最后请求波形。
        """
        try:
            index = self._selected_pretrigger_index()
            frame = command_set_pretrigger(index)
        except ValueError as error:
            messagebox.showerror("预触发错误", str(error))
            return

        label = self.PRETRIGGER_CHOICES[index][0]
        if not self._send(frame, f"已发送预触发 {label} 命令"):
            return

        self.current_pretrigger_index = index
        self._refresh_pretrigger_hint()
        self._update_applied_settings()

        # 预触发档位改变后，已有波形图不再代表新设置，提示重新请求
        if self.latest_waveform_samples and self.latest_waveform_sample_rate_hz:
            self._draw_waveform(
                self.latest_waveform_samples,
                self.latest_waveform_sample_rate_hz,
            )

    def apply_timebase(self):
        try:
            index = self._selected_timebase_index()
            frame = command_set_timebase(index)
        except ValueError as error:
            messagebox.showerror("时基错误", str(error))
            return

        if not self._send(frame, f"已发送时基T{index + 1}命令"):
            return

        self.current_timebase_index = index
        self.worker.set_timebase(index)
        self._invalidate_self_fft()
        self._update_timebase_info()
        self._update_applied_settings()
        self._reset_spectrum_history()
        self._reset_waveform_display()

    def _reset_waveform_display(self):
        """切换时基后清除旧样点，禁止把上一时基的数据按新时间轴重画。

        [10-23] 时间轴固定按 50kHz 算：波形帧已与 0x8D 时基解耦
        （高频档下仍按 50kHz 采），再拿档位的 fs 去算会得到错误窗长
        —— 比如 T4 会算成 0.08ms，实际仍是 20.5ms。
        """
        fs_hz = WAVE_SAMPLE_RATE_HZ
        duration_ms = 1024 * 1000.0 / fs_hz
        self.latest_waveform_samples = None
        self.latest_waveform_sample_rate_hz = None
        self.waveform_frame_times.clear()
        self.waveform_info_var.set(
            f"已切换T{self.current_timebase_index + 1}，请重新请求1024点波形"
        )
        self.export_wave_button.configure(state="disabled")
        self.waveform_frame.configure(text="波形（固定 50 kHz 采样）")
        self.axis.clear()
        self.axis.set_xlabel("时间（ms）")
        self.axis.set_ylabel("ADC码值（LSB）")
        self.axis.set_xlim(0, duration_ms)
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)
        self.canvas.draw_idle()

    def _reset_spectrum_history(self):
        self.latest_spectrum_codes = None
        self.spectrum_history = [[0] * 512 for _ in range(120)]
        self.spectrum_frame_count = 0
        self.spectrum_info_var.set(
            f"已切换T{self.current_timebase_index + 1}，等待新频谱"
        )
        self.export_spectrum_button.configure(state="disabled")
        self._draw_spectrum([0] * 512, count_frame=False)

    # ------------------------------------------------------------------
    # v1.17 电压标定 (0x8C)
    # ------------------------------------------------------------------
    def apply_vpp_cal(self, kn=None):
        """
        发送0x8C电压标定命令。

        kn 省略时从输入框读。两种特殊值：
          1024  -> 原始 LSB 透传(标定第一步: 读原始计数)
          8000  -> 恢复默认 7.8125 mV/LSB

        标定流程(两点法, 实际是"一点定标+满量程假设"):
          1. 点"原始LSB模式", 记下 V 字段的原始计数 N
          2. 用万用表量出真实峰峰值 V_true (mV)
          3. 在输入框填 round(V_true * 1024 / N), 点"应用标定"
        """
        if kn is None:
            try:
                kn = int(self.vpp_kn_var.get().strip())
            except ValueError:
                messagebox.showwarning("KN 无效", "KN 必须是整数(每 LSB 多少 mV x1024)")
                return

        if not 0 <= kn <= 0xFFFF:
            messagebox.showwarning("KN 超范围", "KN 必须在 0～65535 之间")
            return

        if kn == RAW_LSB_KN:
            note = "原始LSB模式(此时 V 字段就是 ADC 计数)"
        elif kn == DEFAULT_VPP_KN:
            note = "默认标定 7.8125 mV/LSB (按 0~2V 量程)"
        else:
            note = f"{kn / 1024:.4f} mV/LSB"

        if not self._send(
            command_set_vpp_cal(kn),
            f"已发送电压标定：KN={kn} ({note})",
        ):
            return

        self.current_vpp_kn = kn
        self.vpp_kn_var.set(str(kn))
        self.vpp_cal_info_var.set(f"当前 KN={kn} ({note})")
        self._update_vpp_unit_display()

    def _vpp_unit(self):
        """KN=1024时V字段是ADC原始计数，其余标定值的单位是mV。"""
        return "LSB" if self.current_vpp_kn == RAW_LSB_KN else "mV"

    def _update_vpp_unit_display(self):
        unit = self._vpp_unit()
        self.vpp_card.configure(text=f"峰峰值 Vpp ({unit})")
        if self.latest_vpp_value is None:
            self.vpp_var.set(f"-- {unit}")
        else:
            self.vpp_var.set(f"{self.latest_vpp_value} {unit}")

        if self.latest_waveform_samples and self.latest_waveform_sample_rate_hz:
            self._update_waveform_info(
                self.latest_waveform_samples,
                self.latest_waveform_sample_rate_hz,
            )

    def export_waveform_csv(self):
        samples = self.latest_waveform_samples
        sample_rate_hz = self.latest_waveform_sample_rate_hz

        if not samples or not sample_rate_hz:
            messagebox.showwarning("没有波形", "请先请求并接收一帧1024点波形")
            return

        path = filedialog.asksaveasfilename(
            title="导出当前波形",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="wavecore_waveform.csv",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["sample_index", "time_ms", "adc_lsb"])
                for index, sample in enumerate(samples):
                    writer.writerow([
                        index,
                        index * 1000.0 / sample_rate_hz,
                        sample,
                    ])
            self.status_var.set(f"波形CSV已导出：{path}")
        except OSError as error:
            messagebox.showerror("波形CSV导出失败", str(error))

    def export_spectrum_csv(self):
        codes = self.latest_spectrum_codes
        if not codes:
            messagebox.showwarning("没有频谱", "请先开始实时频谱并接收一帧512点数据")
            return

        path = filedialog.asksaveasfilename(
            title="导出当前频谱",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="wavecore_spectrum.csv",
        )
        if not path:
            return

        fs_hz = TIMEBASE_SAMPLE_RATES[self.current_timebase_index]
        df_hz = fs_hz / 1024.0
        peak_code = max(codes)
        # 编码每增加16约等于幅度翻倍，即约6.0206 dB。
        db_per_code = 6.0206 / 16.0

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([
                    "timebase",
                    "sample_rate_hz",
                    "bin",
                    "frequency_hz",
                    "magnitude_code",
                    "relative_db_approx",
                ])
                for index, code in enumerate(codes):
                    writer.writerow([
                        f"T{self.current_timebase_index + 1}",
                        fs_hz,
                        index,
                        round(index * df_hz, 6),
                        code,
                        round((code - peak_code) * db_per_code, 3),
                    ])
            self.status_var.set(f"频谱CSV已导出：{path}")
        except OSError as error:
            messagebox.showerror("频谱CSV导出失败", str(error))

    def toggle_csv_logging(self):
        if self.csv_file is not None:
            self.stop_csv_logging()
            return

        path = filedialog.asksaveasfilename(
            title="保存测量记录",
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="wavecore_measurements.csv",
        )
        if not path:
            return

        try:
            # UTF-8 with BOM，用Excel打开中文不易乱码。
            self.csv_file = open(path, "w", newline="", encoding="utf-8-sig")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                "timestamp",
                "frequency_hz",
                "vpp_value",
                "vpp_unit",
                "vpp_kn",
                "peak_s_hz",
                "peak_a_hz",
                "duty_percent",
                "pulse_width_us",
                "waveform_type",
                "self_fft_peak_1_hz",
                "self_fft_peak_2_hz",
                "self_fft_peak_3_hz",
            ])
            self.csv_file.flush()
            self.last_csv_write_time = 0.0
            self.csv_button.configure(text="停止记录CSV", style="Stop.TButton")
            self.status_var.set(f"正在记录CSV：{path}")
        except OSError as error:
            self.csv_file = None
            self.csv_writer = None
            messagebox.showerror("无法创建CSV", str(error))

    def stop_csv_logging(self):
        if self.csv_file is not None:
            try:
                self.csv_file.flush()
                self.csv_file.close()
            except OSError:
                pass

        self.csv_file = None
        self.csv_writer = None
        self.csv_button.configure(text="开始记录CSV", style="Accent.TButton")
        self.status_var.set("CSV记录已停止")

    def _record_measurement(self, event):
        if self.csv_writer is None or self.csv_file is None:
            return

        # FPGA约每10ms上报一次，CSV限制为10行/秒，避免文件过快增长。
        now = time.monotonic()
        if now - self.last_csv_write_time < 0.1:
            return

        try:
            self.csv_writer.writerow([
                datetime.now().isoformat(timespec="milliseconds"),
                event["frequency_hz"],
                event["vpp_mv"],
                self._vpp_unit(),
                self.current_vpp_kn,
                "" if self.latest_peak_s_hz is None else self.latest_peak_s_hz,
                "" if self.latest_peak_a_hz is None else self.latest_peak_a_hz,
                "" if self.latest_duty_percent is None else self.latest_duty_percent,
                "" if self.latest_pulse_width_us is None else self.latest_pulse_width_us,
                "" if self.latest_waveform_type is None else self.latest_waveform_type,
                "" if self.latest_self_fft_peaks["SF"] is None else self.latest_self_fft_peaks["SF"],
                "" if self.latest_self_fft_peaks["S2"] is None else self.latest_self_fft_peaks["S2"],
                "" if self.latest_self_fft_peaks["S3"] is None else self.latest_self_fft_peaks["S3"],
            ])
            self.csv_file.flush()
            self.last_csv_write_time = now
        except OSError as error:
            self.stop_csv_logging()
            messagebox.showerror("CSV写入失败", str(error))

    # ---- 自研 FFT 三峰的读数可信度提示 ----
    #
    # [10-22] 为什么需要这一段：
    #   第三峰通常是方波的五次谐波。基频超过约 5000Hz 时 5f 越过 24.95kHz，
    #   而在 50kHz 采样下它会**混叠折叠**成 50000-5f：
    #       5050Hz -> 5f=25250 -> 读回 24751
    #       5200Hz -> 5f=26000 -> 读回 24002
    #   这些数字看着完全正常，用户会当真值用。
    #
    # ★ 这件事 RTL 发现不了：混叠发生在 ADC 采样那一刻，频谱里那个位置
    #   本来就真有能量，FFT 只是如实报告。能识别它的只有「峰值之间的谐波关系」，
    #   而三个峰只有在主机侧才同时到手。
    #
    #   判据（两条都满足才报）：
    #     1) S2 能被 SF 的 3 倍解释（方波的三次谐波特征）
    #     2) S3 明显偏离 5*SF，且落在 50000-5*SF 附近
    #   只满足 1) 不报 —— 双音等非谐波信号不该被误判。
    SELF_FFT_NYQ_HZ = 24951          # bin 511 对应频率，显示范围上限
    ADC_FS_HZ = 50000                # T1 采样率

    def _self_fft_note(self, values):
        """返回追加在三峰读数后面的短提示；读数可信时返回空串。

        判据只有一条真正可靠：**五次谐波是否越过 24951Hz**。

          5f <= 24951  ->  读数可信（哪怕频率很高，比如 4.95kHz 基频的 24750）
          5f >  24951  ->  已经折叠，读数不可信

        折叠后的频率约等于 fs - 5f：
            5050Hz -> 5f=25250 -> 读回 24751
            5200Hz -> 5f=26000 -> 读回 24002
        这些数字单看完全正常，所以必须显式提示。

        前提是先确认 S2 确实是三次谐波（双音等非谐波信号不该被误判）。
        """
        sf, s2, s3 = values
        if not sf or not s2 or not s3:
            return ""

        # S2 不是 3*SF（5% 容差内）就说明这不是谐波串，不做任何判断
        if abs(s2 - 3 * sf) > 0.05 * 3 * sf:
            return ""

        expect5 = 5 * sf
        if expect5 > self.SELF_FFT_NYQ_HZ:
            return "  <- 第三峰折叠, 5f=%d 已超 24951" % expect5

        # 5f 在范围内但读数对不上，说明第三峰不是五次谐波
        if abs(s3 - expect5) > 0.05 * expect5:
            return "  <- 第三峰非五次谐波"
        return ""

    def _process_events(self):
        while True:
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self.root.after(50, self._process_events)

    def _describe_waveform_type(self, code, names):
        """把 TY 值翻成"能看懂为什么是这个值"的文字。

        [10-18] 用户实测反馈："一直显示识别不出来"。
        查下来板子是好的 —— 串口实际在发 `TY=0`（方波）。
        问题是**可信闸门**：RTL 里

            ty_ok = (freq_hz <= 25kHz) && f_stable
            ty_now = ty_ok ? wave_type : 3

        也就是频率超过 25kHz 就强制报"其他"。而上电默认预设正是 100kHz，
        所以一开机永远是"3：其他"，看上去像识别失败，实际是闸门在工作。

        [10-21 更新] RTL 里那个 `freq_hz <= 25kHz` 的硬闸门已经**没有了**。
        现在的做法是板内按实测频率自适应抽取（`board_top` 的 `wid_decim`），
        实测 1k~25kHz 三档全对且可重复；超过 25kHz 由板子自己报 3，
        因为形状特征确实不够了 —— 这是诚实的"不确定"，不是没跑起来。

        所以界面上看到 3 时，如果频率 >25kHz，说明是信号超出识别范围，
        而不是识别坏了。把原因写在值后面。
        """
        base = f"{code}：{names.get(code, '未知')}"
        if code != 3:
            return base
        f = self.latest_frequency_hz
        if f is None:
            return base
        if f > 25000:
            return f"{base}（超 25kHz）"
        return f"{base}（等稳定）"

    def _handle_event(self, event):
        event_type = event.get("type")

        if event_type == "connected":
            self.connected = True
            port_name = event["port"]
            self.port_var.set(port_name)
            self.connect_button.configure(text="断开", style="Stop.TButton")
            # 0x8D/0x8C都没有ACK。每次首次连接或断线重连后主动重发
            # 当前时基和标定值，避免GUI显示状态与FPGA寄存器状态不一致。
            self.worker.set_timebase(self.current_timebase_index)
            try:
                self.worker.send(command_set_timebase(self.current_timebase_index))
                self.worker.send(command_set_vpp_cal(self.current_vpp_kn))
                self.status_var.set(
                    f"已连接 {port_name} @ {BAUD_RATE}，"
                    f"已同步T{self.current_timebase_index + 1}时基和KN={self.current_vpp_kn}"
                )
            except RuntimeError:
                self.status_var.set(f"已连接 {port_name} @ {BAUD_RATE}")

        elif event_type in {"disconnected", "connection_waiting"}:
            self.connected = False
            self.connect_button.configure(text="连接", style="Accent.TButton")
            self.status_var.set(event["message"])

        elif event_type == "measurement":
            # [10-18] A 行超时清除: FPGA 只在存在第二峰时发 A 行,
            #   1.5 秒内没收到 A 就是"第二峰已经没了" —— 直接显示 "--", 不要留旧值。
            #   **只显示 "-- Hz", 不加中文说明** —— 卡片是实时刷新的,
            #   两峰等幅时会来回互换/闪现, 任何附带的文字都会跟着闪, 反而更难读。
            if (self.latest_peak_a_hz is not None
                    and self._last_peak_a_time > 0
                    and time.monotonic() - self._last_peak_a_time > 1.5):
                self.latest_peak_a_hz = None
                self.peak_a_var.set("-- Hz")
            self.latest_frequency_hz = event["frequency_hz"]
            self.frequency_var.set(f"{event['frequency_hz']} Hz")
            self.latest_vpp_value = event["vpp_mv"]
            self.vpp_var.set(f"{self.latest_vpp_value} {self._vpp_unit()}")
            if self.latest_waveform_samples and self.latest_waveform_sample_rate_hz:
                self._update_waveform_info(
                    self.latest_waveform_samples,
                    self.latest_waveform_sample_rate_hz,
                )
            self._record_measurement(event)

        elif event_type == "peak":
            if event["name"] == "S":
                self.latest_peak_s_hz = event["frequency_hz"]
                self.peak_s_var.set(f"{event['frequency_hz']} Hz")
            else:
                if time.monotonic() < self.suppress_peak_a_until:
                    return
                # [10-18] 原来这里有一条"如果是单音正弦就丢弃 A 行"的过滤，
                #   理由是单音正弦不该有第二峰、收到的 A 是残留。
                #   但它会**误杀 IFFT 演示**：用原始帧(0x87)设双音时 GUI 并不知道
                #   dual_tone_enabled 已经为真，于是双音的第二峰被当成残留丢掉，
                #   界面上永远只有一个峰。
                #   改为**不猜测**：FPGA 发 A 就说明它检测到了第二峰，照实显示。
                #   残留由上面 1.5 秒的超时清除处理（FPGA 不发 A 就自动变 "--"）。
                self.latest_peak_a_hz = event["frequency_hz"]
                self._last_peak_a_time = time.monotonic()
                # [10-18 撤回] 曾在这里加"（主峰包络边带，正常）"的中文标注,
                #   但 S/A 两峰幅度几乎相等、会来回互换, 于是这段文字在两行间
                #   反复切换, 比纯数字更难看。**界面上只给数字。**
                #   边带/残余的区分写在文档里, 不放在实时刷新的卡片上。
                self.peak_a_var.set(f"{event['frequency_hz']} Hz")

        elif event_type == "duty":
            if self.dual_tone_enabled:
                self.latest_duty_percent = None
                self.latest_pulse_width_us = None
                self.duty_var.set("--（双音）")
                self.pulse_width_var.set("--（双音）")
            else:
                self.latest_duty_percent = event["duty_percent"]
                self.latest_pulse_width_us = event["pulse_width_us"]
                self.duty_var.set(f"{event['duty_percent']:.1f} %")
                self.pulse_width_var.set(f"{event['pulse_width_us']} us")

        elif event_type == "waveform_type":
            waveform_names = {0: "方波", 1: "正弦", 2: "三角", 3: "其他"}
            waveform_type = event["waveform_type"]
            self.latest_waveform_type = waveform_type

            # [10-21] 显示策略（解决 25kHz 以上来回跳 + 卡片被撑开）
            #
            # 根因：板上每帧独立判决。25kHz 以上形状特征处在边界，
            #       TY 会在 1/0/2 与 3 之间逐帧跳，界面看着像在抽搐；
            #       而"3：其他（超 25kHz）"比"1：正弦"长一截，卡片跟着伸缩。
            #
            # 做法分两段：
            #   ① 频率 > 25kHz —— **主机自己定性为"其他"**，不用板子的 TY。
            #      主机在同一帧就拿到了频率，判据是确定的，天然不跳。
            #      （只靠去抖不行：50/50 抖动时会一直卡在旧值，反而误导弹。）
            #   ② 频率 ≤ 25kHz —— 识别区可信，直接用板子的 TY；
            #      再加 3 帧一致的去抖，压掉边界上的零星毛刺。
            freq = self.latest_frequency_hz
            if freq is not None and freq > 25000:
                self._ty_pending = 3
                self._ty_streak = self.TY_STREAK_TO_SHOW
                self.detected_waveform_var.set("3：其他（超 25kHz）")
                return

            if waveform_type == self._ty_pending:
                self._ty_streak += 1
            else:
                self._ty_pending = waveform_type
                self._ty_streak = 1

            if self._ty_streak >= self.TY_STREAK_TO_SHOW:
                self.detected_waveform_var.set(
                    self._describe_waveform_type(waveform_type, waveform_names)
                )

        elif event_type == "window_used":
            # [10-18] 每跑一次自研 FFT, 硬件在 SF/S2/S3 之后补一条 WIN= 行
            self.win_used_var.set(event["name"])
            self.latest_window_used = event["code"]
            self._refresh_window_info()

        elif event_type == "self_fft_peak":
            self.latest_self_fft_peaks[event["name"]] = event["frequency_hz"]
            values = [
                self.latest_self_fft_peaks[name]
                for name in ("SF", "S2", "S3")
            ]
            self.self_fft_var.set(
                " / ".join("--" if value is None else str(value) for value in values)
                + " Hz"
                + self._self_fft_note(values)
            )

        elif event_type == "waveform":
            # [10-23] 波形帧固定 50kHz。解析器是按当前档位 fs 填的 sample_rate_hz，
            #   高频档(T3/T4)下会把它当成 12.5MHz，时间轴直接差 250 倍。
            #   这里强制覆盖，不能信解析器传来的值。
            self.latest_waveform_samples = list(event["samples"])
            self.latest_waveform_sample_rate_hz = WAVE_SAMPLE_RATE_HZ
            now = time.monotonic()
            self.waveform_frame_times.append(now)
            self.waveform_frame_times = [
                frame_time
                for frame_time in self.waveform_frame_times
                if now - frame_time <= 5.0
            ]
            self._draw_waveform(
                event["samples"],
                WAVE_SAMPLE_RATE_HZ,
            )
            samples = event["samples"]
            self._update_waveform_info(samples, event["sample_rate_hz"])
            self.export_wave_button.configure(state="normal")
            self.status_var.set(
                f"已收到{len(event['samples'])}点波形"
            )

        elif event_type == "spectrum":
            self._draw_spectrum(event["magnitude_codes"])
            self.status_var.set("已收到512点幅度谱")

        elif event_type == "protocol_error":
            self.status_var.set(f"协议错误：{event['message']}")

    @staticmethod
    def _median_filter_5(samples):
        """仅用于显示的5点滑动中值；不会修改原始数据或导出CSV。"""
        filtered = []
        sample_count = len(samples)
        for index in range(sample_count):
            window = sorted(
                samples[max(0, index - 2):min(sample_count, index + 3)]
            )
            filtered.append(window[len(window) // 2])
        return filtered

    def _display_waveform_samples(self, samples):
        if self.median_filter_var.get():
            return self._median_filter_5(samples)
        return list(samples)

    def _on_waveform_filter_changed(self):
        if not self.latest_waveform_samples or not self.latest_waveform_sample_rate_hz:
            return
        self._draw_waveform(
            self.latest_waveform_samples,
            self.latest_waveform_sample_rate_hz,
        )
        self._update_waveform_info(
            self.latest_waveform_samples,
            self.latest_waveform_sample_rate_hz,
        )

    def _update_waveform_info(self, samples, sample_rate_hz):
        if len(self.waveform_frame_times) >= 2:
            elapsed = self.waveform_frame_times[-1] - self.waveform_frame_times[0]
            frame_rate = (
                (len(self.waveform_frame_times) - 1) / elapsed
                if elapsed > 0
                else 0.0
            )
            frame_rate_text = f"  刷新={frame_rate:.1f} fps"
        else:
            frame_rate_text = ""

        vpp_unit = self._vpp_unit()
        fpga_vpp_text = (
            f"-- {vpp_unit}"
            if self.latest_vpp_value is None
            else f"{self.latest_vpp_value} {vpp_unit}"
        )
        display_samples = self._display_waveform_samples(samples)
        if self.median_filter_var.get():
            filter_text = (
                f"  显示曲线=5点中值，"
                f"显示Vpp={max(display_samples) - min(display_samples)} LSB"
            )
        else:
            filter_text = "  显示曲线=原始"
        self.waveform_info_var.set(
            f"{len(samples)}点  "
            f"fs={sample_rate_hz} Hz  "
            f"min={min(samples)}  max={max(samples)}  "
            f"原始波形Vpp={max(samples) - min(samples)} LSB（含边沿瞬态）  "
            f"FPGA测量Vpp={fpga_vpp_text}"
            f"{filter_text}"
            f"{frame_rate_text}"
        )

    def _draw_waveform(self, samples, sample_rate_hz):
        display_samples = self._display_waveform_samples(samples)
        time_ms = [
            index * 1000.0 / sample_rate_hz
            for index in range(len(samples))
        ]

        self.axis.clear()
        self.axis.plot(time_ms, display_samples, linewidth=1.0, color="#1769aa")

        # [10-21] 两处修正：
        #  ① 触发标记原来固定画在 t=0，但预触发 50% 时触发点其实在帧中央 ——
        #     标记位置是错的。按 PRETRIGGER_RATIO 换算到真实位置。
        #  ② 原来的 set_title（触发信息）紧接着被下面那句 set_title 覆盖，
        #     **从来没显示过**。现在合成一个标题。
        subtitle = (
            f"{len(samples)}点 · {sample_rate_hz / 1000:g} kHz采样"
            + (" · 5点中值滤波" if self.median_filter_var.get() else " · 原始波形")
        )

        if self.applied_trigger_name != "自由":
            ratio = self.PRETRIGGER_RATIO[self.current_pretrigger_index]
            trig_x_ms = ratio * max(len(samples) - 1, 1) * 1000.0 / sample_rate_hz
            self.axis.axvline(
                trig_x_ms, color="#d32f2f", linestyle="--", linewidth=1.1,
                label=f"触发点 {trig_x_ms:.2f} ms",
            )
            pct_text = "%d%%" % int(round(ratio * 100))
            self.axis.set_title(
                f"{subtitle} · 触发：{self.applied_trigger_name} @ "
                f"{trig_x_ms:.2f} ms（预触发 {pct_text}）",
                loc="left",
                color="#d32f2f",
                fontsize=9,
                pad=2,
                bbox={
                    "facecolor": "white",
                    "alpha": 0.88,
                    "edgecolor": "#d32f2f",
                    "pad": 2,
                },
            )
        else:
            self.axis.set_title(subtitle, loc="left", fontsize=9, pad=2)

        self.axis.set_xlabel("时间（ms）")
        self.axis.set_ylabel("ADC码值（LSB）")
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)
        self.canvas.draw_idle()

    def _draw_spectrum(self, magnitude_codes, count_frame=True):
        if len(magnitude_codes) != 512:
            self.status_var.set(
                f"协议错误：幅度谱点数应为512，实际为{len(magnitude_codes)}"
            )
            return

        codes = list(magnitude_codes)
        fs_hz = TIMEBASE_SAMPLE_RATES[self.current_timebase_index]
        df_hz = fs_hz / 1024.0
        # [10-23] 横轴单位按量级自动切：低频档用 kHz，高频档(T3/T4)用 MHz。
        #   原先一律用 kHz，到 T4 会出现「6250 kHz」这种不好读的刻度。
        if fs_hz >= 1_000_000:
            unit = 1_000_000.0
            unit_text = "MHz"
        else:
            unit = 1000.0
            unit_text = "kHz"
        freq_axis = [index * df_hz / unit for index in range(512)]
        span = fs_hz / 2.0 / unit

        if count_frame:
            self.latest_spectrum_codes = codes
            self.spectrum_history.pop(0)
            self.spectrum_history.append(codes)
            self.spectrum_frame_count += 1
            self.export_spectrum_button.configure(state="normal")

        self.spectrum_line.set_data(freq_axis, codes)
        self.spectrum_axis.set_xlim(0, span)
        self.spectrum_axis.set_xlabel(f"频率（{unit_text}）")
        self.spectrum_axis.set_title(
            f"当前频谱 · T{self.current_timebase_index + 1} · "
            f"Δf={df_hz:.2f} Hz",
            fontsize=9,
            pad=2,
        )

        peak_bin = max(range(512), key=codes.__getitem__)
        peak_hz = peak_bin * df_hz
        self.spectrum_peak_text.set_text(
            f"峰值={peak_hz:.1f} Hz · 频点={peak_bin} · 码值={codes[peak_bin]}"
        )

        self.waterfall_image.set_data(self.spectrum_history)
        self.waterfall_image.set_extent(
            [0, span, 0, len(self.spectrum_history)]
        )
        self.waterfall_axis.set_xlim(0, span)

        if count_frame:
            # [10-17] 底噪: 取"离主峰 15 个 bin 以外"的谱线均值。
            #   切窗函数时这个数会明显变化(矩形最高 / Hann最低), 比目测频谱图可靠。
            far = [codes[k] for k in range(512)
                   if abs(k - peak_bin) > 15 and codes[k] > 0]
            floor = (sum(far) / len(far)) if far else 0.0
            # [10-17] 帧率: 开帧重叠后采集时间减半, 这个数会明显上升。
            import time as _time
            now = _time.time()
            if self._spec_last_t is not None and now > self._spec_last_t:
                inst = 1.0 / (now - self._spec_last_t)
                self._spec_fps = (0.7 * self._spec_fps + 0.3 * inst
                                  if self._spec_fps else inst)
            self._spec_last_t = now
            line = (
                f"第{self.spectrum_frame_count}帧｜"
                f"峰值 {peak_hz:.1f} Hz｜"
                f"底噪 {floor:.1f}｜"
                f"{self._spec_fps:.1f} 帧/s｜"
                f"T{self.current_timebase_index + 1} fs={self._fmt_hz(fs_hz)}"
            )
            # [10-23] 谐波越界提示。
            #   用户反馈"频率开高了就没有次峰"——其实是本档 Nyquist 装不下谐波，
            #   2 次/3 次谐波已经折叠回低频。界面直接告诉他该切档，别让人以为坏了。
            nyq_hz = fs_hz / 2.0
            if self.current_timebase_index <= 1 and peak_hz > nyq_hz * 0.4:
                line += f"　⚠ {peak_hz:.0f}Hz 已接近本档上限 {self._fmt_hz(nyq_hz)}，谐波会折叠——切 T3/T4 才能看到次峰"
            self.spectrum_info_var.set(line)

        self.spectrum_canvas.draw_idle()

    def _on_close(self):
        self.auto_waveform_var.set(False)
        self._stop_auto_waveform()
        self.stop_spectrum()
        if self.csv_file is not None:
            try:
                self.csv_file.flush()
                self.csv_file.close()
            except OSError:
                pass
        self.worker.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    WaveCoreApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
