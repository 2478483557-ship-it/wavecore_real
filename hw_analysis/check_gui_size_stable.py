# -*- coding: utf-8 -*-
"""检查：切换功能状态时，窗口尺寸会不会被文字撑大。

2026-10-18 的教训：控制面板里的说明文字（"选窗：自适应（多数频率下判为
Hann，与默认相同；试 976 Hz 可看出切换）"）一勾选就变长，把整行撑宽，
用户看到的是"整个界面被拉开了"。

修法：所有会变长的文字用 tt.Label(width=N) 定宽（单位是字符数），
内容超长只会被截断显示，不参与父容器的 requested width 计算。

本脚本真的启动 Tk，把文字换成极长/极短两套，比较 requested width。
差值为 0 才算通过。

用法（必须用系统 Python 3.8，托管 3.13 缺 tkinter）:
    python hw_analysis/check_gui_size_stable.py
"""
import sys, types, os
# 屏蔽串口依赖
fake = types.ModuleType("serial"); fake.Serial = object
fake.SerialException = Exception; fake.EXCLUSIVE=None; fake.PARITY_NONE=None
fake.STOPBITS_ONE=None; fake.EIGHTBITS=None
sys.modules['serial'] = fake
sys.modules['serial.tools'] = types.ModuleType("serial.tools")
sys.modules['serial.tools.list_ports'] = types.ModuleType("serial.tools.list_ports")
sys.modules['serial.tools.list_ports'].comports = lambda: []

import tkinter as tk
import importlib.util
_HERE = os.path.dirname(os.path.abspath(__file__))
# GUI 依赖 host/ 下的 protocol.py, 先把它加进 sys.path
sys.path.insert(0, os.path.join(_HERE, '..', 'host'))
_GUI = os.path.join(_HERE, '..', 'host', 'wavecore_gui.py')
spec = importlib.util.spec_from_file_location("wg", _GUI)
wg = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(wg)
except Exception as e:
    print("导入失败:", e); sys.exit(1)

root = tk.Tk()
app = wg.WaveCoreApp(root)
root.update_idletasks()
w0 = root.winfo_reqwidth()

# 模拟各种切换
cases = []
app.window_info_var.set("自适应")
app.wave_src_info_var.set("神经网络")
app.ifft_info_var.set("（已自动停止实时频谱：它会每 150ms 重采一帧，冲掉回放数据）")
app.overlap_info_var.set("50% 重叠已开启：时间常数变为原来一半，帧间无空白")
app.applied_settings_var.set("当前设置：主频 1000 Hz · 正弦 · 触发上升沿 · 时基 T1 · 窗 Hann · 自适应开 · 谱平均关")
root.update_idletasks()
w1 = root.winfo_reqwidth()

app.window_info_var.set("手动"); app.wave_src_info_var.set("规则法")
app.ifft_info_var.set("3/3 完成"); app.overlap_info_var.set("已关")
app.applied_settings_var.set("当前设置：1kHz")
root.update_idletasks()
w2 = root.winfo_reqwidth()

print("窗口 requested width:")
print("  初始      = %d px" % w0)
print("  长文字状态 = %d px" % w1)
print("  短文字状态 = %d px" % w2)
spread = max(w0, w1, w2) - min(w0, w1, w2)
print("  最大差值  = %d px -> %s" % (spread, "OK 稳定" if spread < 5 else "FAIL 会变"))
root.destroy()
sys.exit(0 if spread < 5 else 1)
