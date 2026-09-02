# sim/ — 仿真 testbench 与结果

仿真规范和"先仿真、后上板"的开发习惯：

1. testbench 命名：`xxx_tb.v`（如 `dds_top_tb.v`），与源码一一对应
2. testbench 也写文件头（见 `src/README.md` 模板），注明仿真时钟频率
3. 仿真结果（波形截图、日志）保存到本目录，命名如 `dds_sim_1kHz.png`

## 已完成的仿真

| 日期 | 模块 | 仿真内容 | 结果 | 截图/日志 |
|------|------|----------|------|-----------|
| - | - | - | - | - |

## 仿真步骤（Vivado XSim）

1. 在工程里 Add Sources 加入 testbench（Simulation Sources）
2. 左侧 Flow Navigator → Simulation → Run Behavioral Simulation
3. 波形窗口查看信号；Vivado 自带 `xsim` 足够用，不必强上 ModelSim
