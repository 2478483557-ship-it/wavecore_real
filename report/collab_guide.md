# 全队 GitHub 协作须知（09-07）

> 目标：各写各的工位，成果全部进同一个仓库，冲突最小化。

## 一、工位表（谁写哪）

| 谁 | 目录 | 内容 | 边界 |
|---|---|---|---|
| 队长 | `src/` | FPGA/Verilog | 队友不碰 |
| 队长 | `board/` | 协议、XDC、样例 | 协议改动=先全队说+升版本 |
| 队长 | `skill/`、`report/`、README | 经验/进度/文档 | 队友可读可建议 |
| 队友 1 | `host/` | Python 上位机 | 队长不写这里 |
| 队友 2 | `stm32/` | STM32 固件 + 屏工程说明 | 新建目录已就位 |

> ⚠️ **唯一共享文件**：`board/uart_protocol.md`——任何改动先全队确认再升版本号。

## 二、日常流程（GitHub Desktop）

```
1. 开工前：  Pull(把最新拉下来)
2. 写代码：  只在自己工位目录写
3. 完成：    Commit(英文 Summary) → Pull → Push
4. 冲突：    各写各目录基本不会冲突; 万一冲突→截图发队长, 别硬删
```

## 三、新手小抄（转给队友）

> 1. GitHub Desktop 登录 → File → Clone repository → 选 `wavecore`
> 2. 到你的工位目录写代码（队友1=`host/`，队友2=`stm32/`）
> 3. 写完 Commit → 先 Pull → 再 Push
> 4. Push 被拒 = 多半没接受 GitHub 邀请，去邮箱点接受
> 5. 别提交编译产物（`.gitignore` 已挡住 Keil/Python/Vivado 垃圾）

## 四、文件存放约定
- 编译产物、中间文件一律不进仓库（.gitignore 已配好）
- 大文件（如几百 MB 的库/工具链）→ 网盘，别硬塞 git
- 协议/接口改动是"全队事件"，README/任务书同步更新

## 五、验收节奏
- 队友各自按 `report/teammate1_task.md` / `teammate2_task.md` 交付
- 目标：9/12~13 首次全队合体联调（板子+上位机+屏）
