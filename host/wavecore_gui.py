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
)


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


class WaveCoreApp:
    """WaveCore tkinter主界面。"""

    PRESETS = (
        ("100 kHz", 0, 100_000),
        ("200 kHz", 1, 200_000),
        ("500 kHz", 2, 500_000),
        ("1 MHz", 3, 1_000_000),
    )

    # [2026-10-14 收窄] 下拉框只留 T1/T2 —— T3(100k)/T4(200k) 实机切换后无响应，
    #   根因未定位，先从界面上撤掉入口。FPGA 侧四档仍在。
    #   恢复办法见 host/protocol.py 里 TIMEBASE_SAMPLE_RATES 上方的注释。
    TIMEBASE_CHOICES = (
        ("T1  50 kHz", 0),
        ("T2  12.5 kHz", 1),
    )

    # [v1.21 0x8F] 预触发比例：决定触发点在 1024 点波形帧里的位置
    #   0% 与升级前逐位等价；50% 时触发点落在帧正中央，可以看到触发沿左侧的波形
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
        self.latest_self_fft_peaks = {"SF": None, "S2": None, "S3": None}
        self.suppress_peak_a_until = 0.0
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
        self.self_fft_var = tk.StringVar(value="-- / -- / -- Hz")
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
        self.timebase_info_var = tk.StringVar()
        self.spectrum_info_var = tk.StringVar(value="尚未请求频谱")
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
        self.refresh_ports()
        self.root.after(50, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self):
        self.root.title("WaveCore FPGA上位机")
        self.root.geometry("1200x850")
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

        measurements = ttk.Frame(self.root, padding=(12, 3))
        measurements.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            measurements.columnconfigure(column, weight=1)

        self._measurement_card(measurements, 0, "测量频率 F", self.frequency_var)
        self.vpp_card = self._measurement_card(
            measurements, 1, "峰峰值 Vpp (mV)", self.vpp_var
        )
        self._measurement_card(measurements, 2, "FFT主峰 S", self.peak_s_var)
        self._measurement_card(measurements, 3, "FFT第二峰 A", self.peak_a_var)
        self._measurement_card(measurements, 0, "占空比 D", self.duty_var, row=1)
        self._measurement_card(measurements, 1, "脉宽 W", self.pulse_width_var, row=1)
        self._measurement_card(measurements, 2, "波形识别 TY", self.detected_waveform_var, row=1)
        self._measurement_card(measurements, 3, "自研FFT SF/S2/S3", self.self_fft_var, row=1)

        controls = ttk.LabelFrame(self.root, text="信号与采集控制", padding=(10, 7))
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

        ttk.Label(controls, text="预设档位：").grid(row=1, column=0, pady=(6, 0))
        for offset, (label, index, frequency) in enumerate(self.PRESETS, start=1):
            ttk.Button(
                controls,
                text=label,
                command=lambda i=index, f=frequency: self.set_preset(i, f),
            ).grid(row=1, column=offset, padx=4, pady=(6, 0))

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
            pady=(6, 0),
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
            pady=(6, 0),
            sticky="ew",
        )

        ttk.Label(controls, text="输出波形：").grid(row=2, column=0, pady=(6, 0))
        ttk.Combobox(
            controls,
            textvariable=self.waveform_choice_var,
            values=("正弦", "方波", "三角"),
            state="readonly",
            width=10,
        ).grid(row=2, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="应用波形", command=self.set_waveform_choice).grid(
            row=2, column=2, padx=4, pady=(6, 0)
        )

        ttk.Label(controls, text="触发：").grid(row=2, column=3, pady=(6, 0))
        ttk.Combobox(
            controls,
            textvariable=self.trigger_choice_var,
            values=("自由", "上升沿", "下降沿"),
            state="readonly",
            width=10,
        ).grid(row=2, column=4, padx=4, pady=(6, 0))
        ttk.Button(controls, text="应用触发", command=self.set_trigger_choice).grid(
            row=2, column=5, padx=4, pady=(6, 0)
        )
        ttk.Button(
            controls,
            text="运行自研FFT",
            command=self.run_self_fft,
            style="Accent.TButton",
        ).grid(
            row=2, column=6, padx=4, pady=(6, 0)
        )
        ttk.Button(
            controls,
            text="开始扫频",
            command=lambda: self.set_sweep(True),
            style="Accent.TButton",
        ).grid(
            row=2, column=7, padx=4, pady=(6, 0)
        )
        ttk.Button(
            controls,
            text="停止扫频",
            command=lambda: self.set_sweep(False),
            style="Stop.TButton",
        ).grid(
            row=2, column=8, padx=4, pady=(6, 0)
        )

        # ---- 行3: 电压标定 (v1.17, 0x8C) ----
        # Vpp 现在以 mV 上报。KN = 每 LSB 多少 mV x1024(Q10)。
        # "原始LSB"按钮把 KN 设成 1024, 此时 V 字段就是 ADC 计数 —— 标定第一步用它。
        ttk.Label(controls, text="电压标定 KN：").grid(row=3, column=0, pady=(6, 0))
        ttk.Entry(controls, textvariable=self.vpp_kn_var, width=8).grid(
            row=3, column=1, padx=4, pady=(6, 0)
        )
        ttk.Button(controls, text="应用标定", command=self.apply_vpp_cal).grid(
            row=3, column=2, padx=4, pady=(6, 0)
        )
        ttk.Button(
            controls,
            text="原始LSB模式",
            command=lambda: self.apply_vpp_cal(RAW_LSB_KN),
        ).grid(row=3, column=3, padx=4, pady=(6, 0))
        ttk.Button(
            controls,
            text="恢复默认",
            command=lambda: self.apply_vpp_cal(DEFAULT_VPP_KN),
        ).grid(row=3, column=4, padx=4, pady=(6, 0))
        ttk.Label(controls, textvariable=self.vpp_cal_info_var).grid(
            row=3, column=5, columnspan=4, padx=(12, 0), pady=(6, 0), sticky="w"
        )

        # ---- 行4: 时基档位 (v1.20, 0x8D) ----
        ttk.Label(controls, text="采样时基：").grid(row=4, column=0, pady=(6, 0))
        ttk.Combobox(
            controls,
            textvariable=self.timebase_choice_var,
            values=tuple(label for label, _ in self.TIMEBASE_CHOICES),
            state="readonly",
            width=13,
        ).grid(row=4, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="应用时基", command=self.apply_timebase).grid(
            row=4, column=2, padx=4, pady=(6, 0)
        )
        ttk.Label(controls, textvariable=self.timebase_info_var).grid(
            row=4, column=3, columnspan=6, padx=(12, 0), pady=(6, 0), sticky="w"
        )
        # ---- 行5: 预触发比例 (v1.21, 0x8F) ----
        # 静默命令、无 ACK；只能靠波形图上"触发点的位置"判断是否生效。
        # 0%=帧首点即触发点；50%=触发点位于帧正中（可见触发沿左侧波形）。
        ttk.Label(controls, text="预触发：").grid(row=5, column=0, pady=(6, 0))
        ttk.Combobox(
            controls,
            textvariable=self.pretrigger_choice_var,
            values=tuple(label for label, _ in self.PRETRIGGER_CHOICES),
            state="readonly",
            width=13,
        ).grid(row=5, column=1, padx=4, pady=(6, 0))
        ttk.Button(controls, text="应用预触发", command=self.apply_pretrigger).grid(
            row=5, column=2, padx=4, pady=(6, 0)
        )
        ttk.Label(controls, textvariable=self.pretrigger_info_var).grid(
            row=5, column=3, columnspan=6, padx=(12, 0), pady=(6, 0), sticky="w"
        )

        ttk.Label(
            controls,
            textvariable=self.applied_settings_var,
        ).grid(row=6, column=0, columnspan=9, pady=(6, 0), sticky="w")

        self.plot_notebook = ttk.Notebook(self.root)
        self.plot_notebook.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 10))

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

    @staticmethod
    def _measurement_card(parent, column, title, variable, row=0):
        card = ttk.LabelFrame(parent, text=title, padding=(10, 6))
        card.grid(row=row, column=column, sticky="nsew", padx=4, pady=3)
        ttk.Label(card, textvariable=variable, style="Value.TLabel").pack()
        return card

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

    def set_trigger_choice(self):
        choices = {"自由": 0, "上升沿": 1, "下降沿": 2}
        name = self.trigger_choice_var.get()
        trigger_mode = choices.get(name)
        if trigger_mode is None:
            messagebox.showerror("触发错误", "请选择自由、上升沿或下降沿")
            return
        if self._send(command_set_trigger(trigger_mode), f"已设置触发模式：{name}"):
            self.applied_trigger_name = name
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

    def _update_timebase_info(self):
        fs_hz = TIMEBASE_SAMPLE_RATES[self.current_timebase_index]
        resolution_hz = fs_hz / 1024.0
        span_hz = fs_hz / 2.0
        self.timebase_info_var.set(
            f"当前T{self.current_timebase_index + 1}："
            f"fs={fs_hz / 1000:g} kHz，"
            f"Δf={resolution_hz:.2f} Hz，"
            f"频谱范围0～{span_hz / 1000:g} kHz"
        )
        if hasattr(self, "waveform_frame"):
            self.waveform_frame.configure(
                text=(
                    f"波形（T{self.current_timebase_index + 1}，"
                    f"{fs_hz / 1000:g} kHz采样）"
                )
            )

    def _selected_pretrigger_index(self):
        choices = dict(self.PRETRIGGER_CHOICES)
        try:
            return choices[self.pretrigger_choice_var.get()]
        except KeyError as error:
            raise ValueError("请选择0%、25%、50%或75%预触发") from error

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
        ratio = self.PRETRIGGER_RATIO[index]
        if index == 0:
            self.pretrigger_info_var.set("预触发 0%：帧首点 = 触发点（与升级前一致）")
        else:
            self.pretrigger_info_var.set(
                f"预触发 {label}：触发点位于帧内第 {int(1024 * ratio)} 点，"
                f"可见触发沿左侧的波形"
            )
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
        """切换时基后清除旧样点，禁止把上一时基的数据按新时间轴重画。"""
        fs_hz = TIMEBASE_SAMPLE_RATES[self.current_timebase_index]
        duration_ms = 1024 * 1000.0 / fs_hz
        self.latest_waveform_samples = None
        self.latest_waveform_sample_rate_hz = None
        self.waveform_frame_times.clear()
        self.waveform_info_var.set(
            f"已切换T{self.current_timebase_index + 1}，请重新请求1024点波形"
        )
        self.export_wave_button.configure(state="disabled")
        self.waveform_frame.configure(
            text=(
                f"波形（T{self.current_timebase_index + 1}，"
                f"{fs_hz / 1000:g} kHz采样）"
            )
        )
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

    def _process_events(self):
        while True:
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self.root.after(50, self._process_events)

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
                if self.applied_waveform_name == "正弦" and not self.dual_tone_enabled:
                    self.latest_peak_a_hz = None
                    self.peak_a_var.set("-- Hz")
            else:
                if time.monotonic() < self.suppress_peak_a_until:
                    return
                # 单音正弦没有需要展示的第二峰。波形切换瞬间可能还有上一种
                # 波形的A报文滞留在串口中，忽略它可避免GUI和CSV记录旧谐波。
                if self.applied_waveform_name == "正弦" and not self.dual_tone_enabled:
                    self.latest_peak_a_hz = None
                    self.peak_a_var.set("-- Hz")
                    return
                self.latest_peak_a_hz = event["frequency_hz"]
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
            self.detected_waveform_var.set(
                f"{waveform_type}：{waveform_names.get(waveform_type, '未知')}"
            )

        elif event_type == "self_fft_peak":
            self.latest_self_fft_peaks[event["name"]] = event["frequency_hz"]
            values = [
                self.latest_self_fft_peaks[name]
                for name in ("SF", "S2", "S3")
            ]
            self.self_fft_var.set(
                " / ".join("--" if value is None else str(value) for value in values)
                + " Hz"
            )

        elif event_type == "waveform":
            self.latest_waveform_samples = list(event["samples"])
            self.latest_waveform_sample_rate_hz = event["sample_rate_hz"]
            now = time.monotonic()
            self.waveform_frame_times.append(now)
            self.waveform_frame_times = [
                frame_time
                for frame_time in self.waveform_frame_times
                if now - frame_time <= 5.0
            ]
            self._draw_waveform(
                event["samples"],
                event["sample_rate_hz"],
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
        if self.applied_trigger_name != "自由":
            self.axis.axvline(0, color="#d32f2f", linestyle="--", linewidth=1.1)
            trigger_name = {
                "上升沿": "上升沿",
                "下降沿": "下降沿",
            }.get(self.applied_trigger_name, self.applied_trigger_name)
            self.axis.set_title(
                f"触发：{trigger_name}，t=0",
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
        self.axis.set_xlabel("时间（ms）")
        self.axis.set_ylabel("ADC码值（LSB）")
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)
        self.axis.set_title(
            f"{len(samples)}点 · {sample_rate_hz / 1000:g} kHz采样"
            + (" · 5点中值滤波" if self.median_filter_var.get() else " · 原始波形")
        )
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
        frequency_khz = [index * df_hz / 1000.0 for index in range(512)]
        span_khz = fs_hz / 2000.0

        if count_frame:
            self.latest_spectrum_codes = codes
            self.spectrum_history.pop(0)
            self.spectrum_history.append(codes)
            self.spectrum_frame_count += 1
            self.export_spectrum_button.configure(state="normal")

        self.spectrum_line.set_data(frequency_khz, codes)
        self.spectrum_axis.set_xlim(0, span_khz)
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
            [0, span_khz, 0, len(self.spectrum_history)]
        )
        self.waterfall_axis.set_xlim(0, span_khz)

        if count_frame:
            self.spectrum_info_var.set(
                f"第{self.spectrum_frame_count}帧｜"
                f"峰值 {peak_hz:.1f} Hz｜"
                f"T{self.current_timebase_index + 1} fs={fs_hz / 1000:g} kHz"
            )

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
