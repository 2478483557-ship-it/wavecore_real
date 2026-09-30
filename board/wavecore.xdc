# WaveCore M2 board constraints (ALIENTEK Da Vinci Pro, XC7A35T-2FGG484)
# Source: official hs_ad_da.xdc from ALIENTEK example 29_hs_ad_da
# All pins verified against board IO pin table (see board/pin_map.md)
# NOTE: keep this file ASCII-only (comments in English)

# --- clock: 50MHz on board ---
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]

# --- system clock / reset (LVCMOS15, on core board) ---
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN R4} [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN U7} [get_ports sys_rst_n]

# --- M3: key0 & LED ---
# IMPORTANT: key/led/sys_clk/sys_rst are ALL in bank 34 (VCCO=1.5V) on ALIENTEK Da Vinci Pro,
# so they must use LVCMOS15 (official ALIENTEK XDC). Using LVCMOS33 causes DRC BIVC-1.
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN T4} [get_ports key0]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN V9} [get_ports {led[0]}]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN Y8} [get_ports {led[1]}]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN Y7} [get_ports {led[2]}]
set_property -dict {IOSTANDARD LVCMOS15 PACKAGE_PIN W7} [get_ports {led[3]}]

# --- DAC AD9708 via ATK_HS_AD_DA module (LVCMOS33) ---
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C19} [get_ports {da_data[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C18} [get_ports {da_data[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B16} [get_ports {da_data[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B15} [get_ports {da_data[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C15} [get_ports {da_data[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C14} [get_ports {da_data[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B13} [get_ports {da_data[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C13} [get_ports {da_data[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B20} [get_ports da_clk]

# --- ADC AD9280 via ATK_HS_AD_DA module (LVCMOS33, official XDC) ---
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B22} [get_ports {ad_data[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN C22} [get_ports {ad_data[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN B21} [get_ports {ad_data[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN A21} [get_ports {ad_data[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D14} [get_ports {ad_data[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D15} [get_ports {ad_data[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN E16} [get_ports {ad_data[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D16} [get_ports {ad_data[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D20} [get_ports ad_clk]

# --- UART TX to CH340 USB-serial (LVCMOS33, B16 bank) ---
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN D17} [get_ports uart_txd]

# --- UART RX from CH340 (LVCMOS33, B16 bank, M5 commands) ---
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN E14} [get_ports uart_rxd]

## ===== F1 passthrough port: FPGA<->STM32 (2026-09-15) =====
set_property -dict {PACKAGE_PIN N13 IOSTANDARD LVCMOS33} [get_ports uart_stm32_txd]
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports uart_stm32_rxd]
set_property PULLUP true [get_ports uart_stm32_rxd]
