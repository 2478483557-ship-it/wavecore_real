# sim/board_elab — 整顶层(board_top) 端口精化检查

不开 Vivado 的"例化端口对齐"体检：把全部 `src/*.v` + 4 个 IP 行为替身
（`blk_mem_gen_0/1`、`xfft_0`、`ila_0`）一起 `xvlog + xelab board_top`。

- 双击 `run_board_elab.bat`（或 `bash run_board_elab.sh`）；
- **通过标志**：日志里出现 `Built simulation snapshot`；
- 改了任何例化/端口后必跑（比等 8~15 分钟综合快得多）；
- 本目录的源码拷贝是生成物（已被本目录 .gitignore 排除），手写的只有两个 run 脚本、
  `blk_mem_gen_0.v`、`ila_0.v` 四个文件。
