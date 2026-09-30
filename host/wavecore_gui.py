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

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from protocol import (
    DEFAULT_VPP_KN,
    RAW_LSB_KN,
    StreamParser,
    command_request_waveform,
    command_run_self_fft,
    command_set_frequency,
    command_set_preset,
    command_set_second_frequency,
    command_set_sweep,
    command_set_trigger,
    command_set_vpp_cal,
    command_set_waveform,
)


BAUD_RATE = 460800
RECONNECT_INTERVAL_SECONDS = 1.0
CH340_VID = 0x1A86
CH340_PIDS = {0x7523, 0x5523}


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

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, port_name):
        self.stop()
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
            except serial.SerialException:
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
            except serial.SerialException:
                pass
        self._serial = None
        self.current_port = None

    def _run(self):
        parser = StreamParser()
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
                    parser = StreamParser()
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
        self.waveform_info_var = tk.StringVar(value="尚未请求波形")
        # v1.17 电压标定: kn = 每 LSB 多少 mV x1024 (Q10); 8000 = 7.8125 mV/LSB
        self.vpp_kn_var = tk.StringVar(value=str(DEFAULT_VPP_KN))
        self.vpp_cal_info_var = tk.StringVar(
            value=f"当前 KN={DEFAULT_VPP_KN} (7.8125 mV/LSB, 按 0~2V 量程)"
        )

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self.refresh_ports()
        self.root.after(50, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self):
        self.root.title("WaveCore FPGA上位机")
        self.root.geometry("1100x720")
        self.root.minsize(900, 620)

    def _configure_styles(self):
        style = ttk.Style()
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("CardTitle.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10))

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        connection = ttk.LabelFrame(self.root, text="串口连接", padding=10)
        connection.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
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
        )
        self.connect_button.grid(row=0, column=3, padx=6)
        ttk.Label(connection, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=4, padx=(12, 0), sticky="e"
        )

        measurements = ttk.Frame(self.root, padding=(12, 6))
        measurements.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            measurements.columnconfigure(column, weight=1)

        self._measurement_card(measurements, 0, "测量频率 F", self.frequency_var)
        self._measurement_card(measurements, 1, "峰峰值 Vpp (mV)", self.vpp_var)
        self._measurement_card(measurements, 2, "FFT主峰 S", self.peak_s_var)
        self._measurement_card(measurements, 3, "FFT第二峰 A", self.peak_a_var)
        self._measurement_card(measurements, 0, "占空比 D", self.duty_var, row=1)
        self._measurement_card(measurements, 1, "脉宽 W", self.pulse_width_var, row=1)
        self._measurement_card(measurements, 2, "波形识别 TY", self.detected_waveform_var, row=1)
        self._measurement_card(measurements, 3, "自研FFT SF/S2/S3", self.self_fft_var, row=1)

        controls = ttk.LabelFrame(self.root, text="信号源控制", padding=10)
        controls.grid(row=2, column=0, sticky="ew", padx=12, pady=6)

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
        ttk.Button(controls, text="开启双音", command=self.enable_dual_tone).grid(
            row=0, column=7, padx=4
        )
        ttk.Button(controls, text="恢复单音", command=self.restore_single_tone).grid(
            row=0, column=8, padx=4
        )

        ttk.Label(controls, text="预设档位：").grid(row=1, column=0, pady=(10, 0))
        for offset, (label, index, frequency) in enumerate(self.PRESETS, start=1):
            ttk.Button(
                controls,
                text=label,
                command=lambda i=index, f=frequency: self.set_preset(i, f),
            ).grid(row=1, column=offset, padx=4, pady=(10, 0))

        self.csv_button = ttk.Button(
            controls,
            text="开始记录CSV",
            command=self.toggle_csv_logging,
        )
        self.csv_button.grid(
            row=1,
            column=5,
            columnspan=2,
            padx=4,
            pady=(10, 0),
            sticky="ew",
        )

        ttk.Button(
            controls,
            text="请求1024点波形",
            command=self.request_waveform,
        ).grid(row=1, column=7, columnspan=2, padx=4, pady=(10, 0), sticky="ew")

        ttk.Label(controls, text="输出波形：").grid(row=2, column=0, pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.waveform_choice_var,
            values=("正弦", "方波", "三角"),
            state="readonly",
            width=10,
        ).grid(row=2, column=1, padx=4, pady=(10, 0))
        ttk.Button(controls, text="应用波形", command=self.set_waveform_choice).grid(
            row=2, column=2, padx=4, pady=(10, 0)
        )

        ttk.Label(controls, text="触发：").grid(row=2, column=3, pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.trigger_choice_var,
            values=("自由", "上升沿", "下降沿"),
            state="readonly",
            width=10,
        ).grid(row=2, column=4, padx=4, pady=(10, 0))
        ttk.Button(controls, text="应用触发", command=self.set_trigger_choice).grid(
            row=2, column=5, padx=4, pady=(10, 0)
        )
        ttk.Button(controls, text="运行自研FFT", command=self.run_self_fft).grid(
            row=2, column=6, padx=4, pady=(10, 0)
        )
        ttk.Button(controls, text="开始扫频", command=lambda: self.set_sweep(True)).grid(
            row=2, column=7, padx=4, pady=(10, 0)
        )
        ttk.Button(controls, text="停止扫频", command=lambda: self.set_sweep(False)).grid(
            row=2, column=8, padx=4, pady=(10, 0)
        )

        # ---- 行3: 电压标定 (v1.17, 0x8C) ----
        # Vpp 现在以 mV 上报。KN = 每 LSB 多少 mV x1024(Q10)。
        # "原始LSB"按钮把 KN 设成 1024, 此时 V 字段就是 ADC 计数 —— 标定第一步用它。
        ttk.Label(controls, text="电压标定 KN：").grid(row=3, column=0, pady=(10, 0))
        ttk.Entry(controls, textvariable=self.vpp_kn_var, width=8).grid(
            row=3, column=1, padx=4, pady=(10, 0)
        )
        ttk.Button(controls, text="应用标定", command=self.apply_vpp_cal).grid(
            row=3, column=2, padx=4, pady=(10, 0)
        )
        ttk.Button(
            controls,
            text="原始LSB模式",
            command=lambda: self.apply_vpp_cal(RAW_LSB_KN),
        ).grid(row=3, column=3, padx=4, pady=(10, 0))
        ttk.Button(
            controls,
            text="恢复默认",
            command=lambda: self.apply_vpp_cal(DEFAULT_VPP_KN),
        ).grid(row=3, column=4, padx=4, pady=(10, 0))
        ttk.Label(controls, textvariable=self.vpp_cal_info_var).grid(
            row=3, column=5, columnspan=4, padx=(12, 0), pady=(10, 0), sticky="w"
        )

        waveform = ttk.LabelFrame(self.root, text="波形（50 kHz采样）", padding=8)
        waveform.grid(row=3, column=0, sticky="nsew", padx=12, pady=(6, 12))
        waveform.columnconfigure(0, weight=1)
        waveform.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.axis.set_xlabel("Time (ms)")
        self.axis.set_ylabel("ADC (LSB)")
        self.axis.set_xlim(0, 20.48)
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)
        self.figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.figure, master=waveform)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        waveform_actions = ttk.Frame(waveform)
        waveform_actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        waveform_actions.columnconfigure(0, weight=1)
        ttk.Label(
            waveform_actions,
            textvariable=self.waveform_info_var,
        ).grid(row=0, column=0, sticky="w")
        self.export_wave_button = ttk.Button(
            waveform_actions,
            text="导出当前波形CSV",
            command=self.export_waveform_csv,
            state="disabled",
        )
        self.export_wave_button.grid(row=0, column=1, sticky="e")

    @staticmethod
    def _measurement_card(parent, column, title, variable, row=0):
        card = ttk.LabelFrame(parent, text=title, padding=12)
        card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        ttk.Label(card, textvariable=variable, style="Value.TLabel").pack()

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
            self.connect_button.configure(text="连接")
            return

        port_name = self.port_var.get().strip()
        if not port_name:
            messagebox.showwarning("未选择串口", "请先刷新并选择串口")
            return

        self.status_var.set("正在连接……")
        self.connect_button.configure(text="断开")
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
            self.latest_peak_a_hz = None
            self.peak_a_var.set("-- Hz")
            self.suppress_peak_a_until = time.monotonic() + 1.0

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
            self.suppress_peak_a_until = 0.0

    def restore_single_tone(self):
        self.set_main_frequency()

    def set_preset(self, index, frequency):
        frame = command_set_preset(index)
        if self._send(frame, f"已发送预设档位 {frequency} Hz"):
            self.main_frequency_var.set(str(frequency))
            self.latest_peak_a_hz = None
            self.peak_a_var.set("-- Hz")
            self.suppress_peak_a_until = time.monotonic() + 1.0

    def request_waveform(self):
        self._send(command_request_waveform(), "已请求波形，等待1024点数据")

    def set_waveform_choice(self):
        choices = {"正弦": 0, "方波": 1, "三角": 2}
        name = self.waveform_choice_var.get()
        waveform_type = choices.get(name)
        if waveform_type is None:
            messagebox.showerror("波形错误", "请选择正弦、方波或三角")
            return
        self._send(command_set_waveform(waveform_type), f"已切换输出波形：{name}")

    def set_trigger_choice(self):
        choices = {"自由": 0, "上升沿": 1, "下降沿": 2}
        name = self.trigger_choice_var.get()
        trigger_mode = choices.get(name)
        if trigger_mode is None:
            messagebox.showerror("触发错误", "请选择自由、上升沿或下降沿")
            return
        self._send(command_set_trigger(trigger_mode), f"已设置触发模式：{name}")

    def run_self_fft(self):
        self.latest_self_fft_peaks = {"SF": None, "S2": None, "S3": None}
        self.self_fft_var.set("等待结果……")
        self._send(command_run_self_fft(), "已请求运行一次自研FFT")

    def set_sweep(self, enabled):
        action = "开始" if enabled else "停止"
        self._send(command_set_sweep(enabled), f"已发送{action}扫频命令")

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

        self.vpp_kn_var.set(str(kn))
        self._send(command_set_vpp_cal(kn), f"已发送电压标定：KN={kn} ({note})")
        self.vpp_cal_info_var.set(f"当前 KN={kn} ({note})")

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
                "vpp_mv",
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
            self.csv_button.configure(text="停止记录CSV")
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
        self.csv_button.configure(text="开始记录CSV")
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
            self.status_var.set(f"已连接 {port_name} @ {BAUD_RATE}")
            self.connect_button.configure(text="断开")

        elif event_type in {"disconnected", "connection_waiting"}:
            self.connected = False
            self.status_var.set(event["message"])

        elif event_type == "measurement":
            self.frequency_var.set(f"{event['frequency_hz']} Hz")
            self.vpp_var.set(f"{event['vpp_mv']} mV")
            self._record_measurement(event)

        elif event_type == "peak":
            if event["name"] == "S":
                self.latest_peak_s_hz = event["frequency_hz"]
                self.latest_peak_a_hz = None
                self.peak_s_var.set(f"{event['frequency_hz']} Hz")
                self.peak_a_var.set("-- Hz")
            else:
                if time.monotonic() < self.suppress_peak_a_until:
                    return
                self.latest_peak_a_hz = event["frequency_hz"]
                self.peak_a_var.set(f"{event['frequency_hz']} Hz")

        elif event_type == "duty":
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
            self._draw_waveform(
                event["samples"],
                event["sample_rate_hz"],
            )
            samples = event["samples"]
            self.waveform_info_var.set(
                f"{len(samples)}点  "
                f"fs={event['sample_rate_hz']} Hz  "
                f"min={min(samples)}  max={max(samples)}  "
                f"Vpp={max(samples) - min(samples)} LSB (波形帧原始ADC)"
            )
            self.export_wave_button.configure(state="normal")
            self.status_var.set(
                f"已收到{len(event['samples'])}点波形"
            )

        elif event_type == "protocol_error":
            self.status_var.set(f"协议错误：{event['message']}")

    def _draw_waveform(self, samples, sample_rate_hz):
        time_ms = [
            index * 1000.0 / sample_rate_hz
            for index in range(len(samples))
        ]

        self.axis.clear()
        self.axis.plot(time_ms, samples, linewidth=1.0, color="#1769aa")
        self.axis.set_xlabel("Time (ms)")
        self.axis.set_ylabel("ADC (LSB)")
        self.axis.set_ylim(0, 255)
        self.axis.grid(alpha=0.3)
        self.axis.set_title(
            f"{len(samples)} samples @ {sample_rate_hz / 1000:.0f} kHz"
        )
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _on_close(self):
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
