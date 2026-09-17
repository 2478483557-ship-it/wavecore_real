# WaveCore Python上位机

本目录是WaveCore的电脑端上位机，用于连接FPGA板卡、显示测量结果、控制DDS信号源和查看1024点波形。

## 功能

- 自动识别CH340串口，460800-8N1连接(v1.8 提速)。
- 实时显示测量频率F、Vpp原始计数、FFT主峰S和第二峰A。
- 发送0x85设置1～12500000 Hz主频。
- 发送0x87开启第二频率，支持双音测试。
- 发送0x81切换100 kHz、200 kHz、500 kHz和1 MHz预设档位。
- 发送0x83请求1024点、50 kHz采样波形并在界面中绘制。
- 测量结果记录为CSV，最多10行/秒。
- 导出当前1024点波形CSV。
- 串口断开后每1秒尝试重连，COM号变化时重新寻找唯一的CH340设备。
- 同时兼容新固件的 `\r\n` 和旧固件的 `\r` 行尾。

## 运行环境

- Python 3.13（其他近期Python 3版本也可尝试）
- pyserial 3.5
- matplotlib 3.11
- tkinter 8.6（Windows Python安装程序通常自带）

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

## 连接

1. 断电时插好AD/DA模块和DA→AD回环线。
2. 给FPGA板卡上电并打开开关。
3. 用USB连接板载CH340和电脑。
4. 确认Windows设备管理器出现 `USB-SERIAL CH340 (COMx)`。
5. 关闭XCOM、串口助手及其他占用该COM口的程序。

## 启动

```powershell
cd wavecore_real-main\host
python wavecore_gui.py
```

界面打开后选择COM口并点击“连接”。

## 推荐演示流程

1. 主频输入 `1000`，点击“设置主频”。
2. 确认F约为1000 Hz，S约为1001 Hz。
3. 点击“请求1024点波形”，确认显示约20个正弦周期。
4. 第二频率输入 `1100`，点击“开启双音”。
5. 确认S/A中出现约1001 Hz和1099 Hz两个谱峰。
6. 点击“恢复单音”，第二峰恢复为 `-- Hz`。

双音时F受拍频影响会波动，S/A的主次顺序也可能交换，均为正常现象。

## CSV文件

实时测量CSV列：

```text
timestamp,frequency_hz,vpp_lsb,peak_s_hz,peak_a_hz
```

波形CSV列：

```text
sample_index,time_ms,adc_lsb
```

单音没有第二峰时，`peak_a_hz` 留空。Vpp是ADC原始计数差，单位为LSB，不是电压。

## 调试脚本

协议自检：

```powershell
python protocol.py
```

终端串口测试：

```powershell
python serial_test.py COM4 1000
python serial_test.py COM4 1000 1100
python serial_test.py COM4 1000 --wave
```

完整硬件冒烟测试：

```powershell
python hardware_smoke_test.py COM4
```

## 常见问题

- `PermissionError` 或“Access denied”：其他程序占用了串口。
- 看不到COM口：检查USB线、板卡电源和CH340驱动。
- F正常而S异常：看波形和FFT时将信号设为20 kHz以下。
- 中文终端乱码：先执行 `chcp 65001`。
- 波形请求失败：确认固件支持0x83，并关闭其他串口程序。
