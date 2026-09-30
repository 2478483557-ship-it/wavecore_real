# -*- coding: utf-8 -*-
"""WaveCore上位机硬件冒烟测试。"""

import queue
import sys
import time

from protocol import (
    command_request_waveform,
    command_set_frequency,
    command_set_second_frequency,
)
from wavecore_gui import SerialWorker


def wait_for(worker, predicate, timeout, label):
    deadline = time.monotonic() + timeout
    seen = []

    while time.monotonic() < deadline:
        try:
            event = worker.events.get(timeout=0.2)
        except queue.Empty:
            continue

        seen.append(event)
        event_type = event.get("type")
        if event_type in {"connection_waiting", "disconnected", "protocol_error"}:
            print(f"[{event_type}] {event.get('message', event)}")

        if predicate(event, seen):
            print(f"[PASS] {label}")
            return event, seen

    raise TimeoutError(f"[FAIL] {label}，{timeout}秒内未收到预期结果")


def main():
    port_name = sys.argv[1] if len(sys.argv) >= 2 else "COM4"
    worker = SerialWorker()

    try:
        print(f"[1/4] 连接 {port_name}")
        worker.start(port_name)
        wait_for(
            worker,
            lambda event, _seen: event.get("type") == "connected",
            5,
            "串口连接",
        )

        print("[2/4] 设置1kHz并验证F/S")
        worker.send(command_set_frequency(1000))

        _, frequency_events = wait_for(
            worker,
            lambda event, _seen: (
                event.get("type") == "measurement"
                and 990 <= event.get("frequency_hz", 0) <= 1010
            ),
            5,
            "F约等1000Hz",
        )

        _, peak_events = wait_for(
            worker,
            lambda event, _seen: (
                event.get("type") == "peak"
                and event.get("name") == "S"
                and 990 <= event.get("frequency_hz", 0) <= 1010
            ),
            6,
            "S约等1001Hz",
        )

        measurements = [
            event
            for event in frequency_events + peak_events
            if event.get("type") == "measurement"
        ]
        if measurements:
            latest = measurements[-1]
            print(
                f"      F={latest['frequency_hz']}Hz, "
                f"Vpp={latest['vpp_mv']} mV"
            )

        print("[3/4] 开启1.1kHz第二频率并验证双峰")
        worker.send(command_set_second_frequency(1100))

        def has_both_peaks(_event, seen):
            peaks = {
                event.get("frequency_hz")
                for event in seen
                if event.get("type") == "peak"
            }
            has_1k = any(990 <= value <= 1010 for value in peaks)
            has_1_1k = any(1090 <= value <= 1110 for value in peaks)
            return has_1k and has_1_1k

        _, dual_events = wait_for(
            worker,
            has_both_peaks,
            8,
            "FFT同时检出1kHz和1.1kHz",
        )
        dual_peaks = sorted({
            event["frequency_hz"]
            for event in dual_events
            if event.get("type") == "peak"
        })
        print(f"      观察到的谱峰：{dual_peaks}")

        print("[4/4] 恢复1kHz单音并请求1024点波形")
        worker.send(command_set_frequency(1000))
        time.sleep(0.3)
        worker.send(command_request_waveform())

        waveform, _ = wait_for(
            worker,
            lambda event, _seen: (
                event.get("type") == "waveform"
                and len(event.get("samples", [])) == 1024
            ),
            6,
            "1024点波形长度和校验",
        )
        samples = waveform["samples"]
        print(
            f"      fs={waveform['sample_rate_hz']}Hz, "
            f"min={min(samples)}, max={max(samples)}, "
            f"Vpp={max(samples) - min(samples)} LSB (波形帧原始ADC)"
        )

        print("[RESULT] 硬件冒烟测试全部通过")

    finally:
        worker.stop()


if __name__ == "__main__":
    main()
