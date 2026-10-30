# report/ 文档索引

> 本目录存放设计报告、技术专题与验证记录。
> **交付用的三份正式文档在桌面 `嵌赛文件/`，不在本目录**：
> 技术文档（35 页）、工程技能包（47 页 / 73 条）、大模型协作记录（37 页 / 49 条）。

---

## 一、评委最可能看的

| 文件 | 内容 |
|---|---|
| `design_report.md` | **设计报告**：系统架构、关键设计、优化过程、资源与时序、验证方法 |
| `demo_package.md` | **现场演示材料包**：一页演示脚本（动作 → 预期 → HEX 帧） |
| `accuracy_calibration.md` | 精度标定：电压、频率的实测与偏差统计 |
| `engineering_challenges.md` | **工程问题复盘**：12 个真实案例，每个含现象、根因、修法 |
| `lut_slim_report.md` | 资源攻坚全过程：LUT 100.14% 超容 → 20,829 → 5,117 的根因分析与闭环证据 |
| `resource_compare.md` | 自研 FFT 与厂商 IP 的同口径资源对比 |
| `t3t4_disable_2026-10-14.md` | 时基 T3/T4 为何撤除（诚实说明 + 恢复方法） |
| `sensor_frontend_guide.md` | 传感器前端选型与接线方案（选型留档；**实测结果见 `sensor_lockin_demo.md` 与技术文档图 3-5/3-6**） |
| `sensor_lockin_demo.md` | 外部声源接入麦克风模块的完整操作单（**2026-10-26 已实测**，−3dB 全宽 47 Hz） |

## 二、技术专题

| 文件 | 内容 |
|---|---|
| `self_fft_design.md` | 自研 1024 点 Radix-2 DIF FFT 的结构与取舍 |
| `fft_design.md` | FFT 定点化与位宽推导 |
| `wave_feat_design.md` | 波形特征提取（6 特征、峭度链路、时序修复） |
| `denoise_experiments.md` | 四层数字抗噪的对比实验 |
| `benchmark.md` | 性能基准数据 |
| `bandwidth_budget.md` | 模拟链路带宽预算 |
| `link_bandwidth_measured.md` | 模拟链路频响实测（−3dB > 1MHz） |

## 三、演示与视频素材

| 文件 | 内容 |
|---|---|
| `demo_new_features.md` | 新增六项功能的演示脚本（含可直接粘贴的帧） |
| `ifft_operation_guide.md` | **IFFT 频域滤波 + DAC 回放完整操作指南**（含毛刺排查表） |
| `video_subtitle_data.md` | 视频字幕数据（核心指标 + 分镜字幕表） |
| `video_new_features_text.md` | 新增功能段的字幕与旁白底稿 |
| `video_subtitle_append.md` | 资源利用与三项功能的详细字幕 |
| `submission_checklist.md` | 提交清单与核对项 |

## 四、协作记录

| 文件 | 内容 |
|---|---|
| `llm_collab_log.md` | **大模型协作记录**：44 条，每条含提示词、模型回答、自我纠错轨迹 |

---

## 配图

`figures/` 存放技术文档引用的配图：

- `fig_system_block.png` — 系统整体框图
- `fig_resource_before_after.png` — 资源整改前后对比
- `fig_pretrigger_tiers.png` — 预触发四档示意

## 已移除的过程性文档

仓库不再保留：每日会话总结（`session_summary_*`）、单次验证记录（`verify_result_*`）、
历次升级计划（`upgrade_*`）、内部待办与排期（`backlog`/`progress_log`/`todo_*`）、
队友协作交接（STM32 方案已取消）、学习笔记与面试准备材料等。

这些属于开发过程产物，对理解设计结论没有帮助。**保留的是结论、证据与可复现的方法。**
