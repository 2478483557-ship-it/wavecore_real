# 达芬奇Pro 关键引脚映射（Pin Map）

> 依据：官方《达芬奇Pro开发板IO引脚分配表.xlsx》+ 官方例程 29_hs_ad_da 的 hs_ad_da.xdc（2026-09-02 核对）。
> 写 XDC 约束时直接抄这张表，**不要凭记忆写管脚号**。

## 基础信号

| 信号 | FPGA 管脚 | 电平标准 | 说明 |
|---|---|---|---|
| sys_clk | R4 | LVCMOS15 | 50MHz 板载晶振 |
| sys_rst_n | U7 | LVCMOS15 | 复位，低有效 |
| key[0..3] | T4 T3 R6 T6 | **LVCMOS15** | 按键（bank34 = 1.5V 域，官方 XDC 核实 9/3） |
| touch_key | V8 | **LVCMOS15** | 触摸按键（bank34） |
| led[0..3] | V9 Y8 Y7 W7 | **LVCMOS15** | LED（bank34） |
| beep | V7 | **LVCMOS15** | 蜂鸣器（bank34） |
| uart_rxd | E14 | LVCMOS33 | USB 串口接收（CH340）→ 上位机 |
| uart_txd | D17 | LVCMOS33 | USB 串口发送（CH340）→ 上位机 |
| uart2_rxd | E13 | LVCMOS33 | ATK 模块口接收 |
| uart2_txd | D16 | LVCMOS33 | ATK 模块口发送（**与 ad_data[0] 冲突，勿同时用**） |
| rs485_uart_rxd | R18 | LVCMOS33 | RS485 接收 |
| rs485_uart_txd | T18 | LVCMOS33 | RS485 发送 |
| can_rxd | AA19 | LVCMOS33 | CAN 接收 |
| can_txd | AB20 | LVCMOS33 | CAN 发送 |
| XADC_VP | L10 | — | XADC 正输入（底板排针，经 49.9Ω） |
| XADC_VN | M9 | — | XADC 负输入 |

## ATK_HS_AD_DA 模块（AD9708 + AD9280，官方 XDC，LVCMOS33）

| 信号 | 管脚 | | 信号 | 管脚 |
|---|---|---|---|---|
| da_data[7] | C19 | | ad_data[7] | B22 |
| da_data[6] | C18 | | ad_data[6] | C22 |
| da_data[5] | B16 | | ad_data[5] | B21 |
| da_data[4] | B15 | | ad_data[4] | A21 |
| da_data[3] | C15 | | ad_data[3] | D14 |
| da_data[2] | C14 | | ad_data[2] | D15 |
| da_data[1] | B13 | | ad_data[1] | E16 |
| da_data[0] | C13 | | ad_data[0] | D16 |
| da_clk | B20 | | ad_clk | D20 |
| | | | ad_otr（溢出标志） | C20 |

## 官方 XDC 原文（可直接用）

```tcl
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN R4} [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN U7} [get_ports sys_rst_n]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C19} [get_ports {da_data[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C18} [get_ports {da_data[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B16} [get_ports {da_data[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B15} [get_ports {da_data[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C15} [get_ports {da_data[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C14} [get_ports {da_data[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B13} [get_ports {da_data[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C13} [get_ports {da_data[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B20} [get_ports da_clk]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B22} [get_ports {ad_data[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C22} [get_ports {ad_data[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B21} [get_ports {ad_data[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN A21} [get_ports {ad_data[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D14} [get_ports {ad_data[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D15} [get_ports {ad_data[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN E16} [get_ports {ad_data[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D16} [get_ports {ad_data[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D20} [get_ports ad_clk]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C20} [get_ports ad_otr]
```

## 注意

1. ad_data[0]=D16 与 uart2_txd 同管脚、ad_data[1]=E16 与 gbc_key 同管脚：**插 ATK_HS_AD_DA 模块时禁用 4 针 ATK 模块口**，反之亦然
2. 官方例程工程用 Vivado 2020.2 创建，本机 2020.1 打不开官方 prj；自建工程，源码与 XDC 直接参考
3. XADC 排针在底板，接麦克风做音频彩蛋（模拟输入，经 49.9Ω 到 L10/M9）
