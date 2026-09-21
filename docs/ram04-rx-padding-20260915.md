# RAM-04：JT808 接收状态结构体填充优化

2026-09-15，针对 `build/quality-audit-20260912/REPORT.md` 的 RAM-04。

## 修改与边界

仅调整 `src/jt808.c` 内部 `rx_assembly_t` 字段顺序：
`raw, pos, generation, in_frame` → `raw, pos, in_frame, generation`。
把标志放进 generation 前的对齐空隙，不使用 packed。
该类型与 `s_rx[2]` 均为文件内部状态；使用点只有按字段读写、按通道取地址、
初始化时整体清零。传给解析器的是 raw 数组，没有整体字节序列化、持久化或公共 ABI 依赖。
512 B 容量、双通道隔离、generation 切换与解析行为不变。

## 本轮 ARM 构建证据

基于当前工作树（包含用户原有未提交修改）先构建 before，再仅重排字段构建 after。
使用 Makefile 与 ARM GNU 14.3.rel1；独立目录 `build/ram04-before`、`build/ram04-after`，
未覆盖既有发布镜像，也未修改版本号。

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| ARM sizeof(rx_assembly_t) | 524 B | 520 B |
| offsetof(raw / pos / generation / in_frame) | 0 / 512 / 516 / 520 | 0 / 512 / 516 / 514 |
| ELF s_rx.lto_priv.0 | 1048 B | 1040 B |
| size: text | 104788 B | 104812 B |
| size: data | 304 B | 304 B |
| size: bss（含链接保留区） | 20680 B | 20672 B |

实测静态 RAM 节省 8 B，代价是该构建 Flash 增加 24 B。
Flash guard 通过，镜像占用 105128/106496 B，剩余 1368 B，仍有 LOW_HEADROOM 警告。
不能将这项局部收益描述为解决 RAM 或 Flash 容量瓶颈。

ELF SHA-256：

- before：`bbe7dfd32e9860d00c57c5684c5831c714da82e9e5c203c4e3de602a5f0fc350`
- after：`6252b80cba568599f288fe06d204aa9d0730f2ffc2553d727711b5260e7763fe`

## 验证命令与结果

- `mingw32-make.cmd all BUILD=build/ram04-before` 和 `... BUILD=build/ram04-after`：构建及 Flash guard 通过。日志在 `build/ram04-before.log`、`build/ram04-after.log`。环境无 `make` 命令，使用仓库包装入口。
- `arm-none-eabi-size` 与 `arm-none-eabi-nm -S` 检查两个 ELF：结果如上。
- 从实际源码提取类型，使用 `arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -std=c99 -c` 编译 sizeof/offsetof 常量，`arm-none-eabi-objdump -s -j .rodata` 检查：结果如上；探针及输出保留在两个目录的 `layout.c/.o/.txt`。
- `python tools/tests/test_jt808_dual_session.py`：修改前后通过；复用用户已修改的测试，覆盖双通道最大 512 B 帧交错、主通道半包重连失效、备通道继续接收及重新认证。
- `python tools/tests/test_jt808_session.py`、`python tools/tests/test_jt808_session_send_failure.py`：最终修改后通过。
- `mingw32-make.cmd ram-guard BUILD=build/ram04-after`：失败；已知调用帧 2520 B、静态 RAM 17896 B、扣除已知帧后剩余 4160 B，但全程序栈/堆/异常上界证据不完整。包装脚本返回码未传播此失败，因此另行直接运行 `python tools/map_ram_guard.py app build/ram04-after/a300_firmware.map`，确认退出码 1。
- `git diff --check`：通过（仅有工作树换行符提示）。

本轮仅修改上述源码与本文档，保留已有测试及其他工作树改动。未提交、部署或烧录。
主备链路真实接收/重连、主循环及 IRQ 延迟需要实机/HIL 验证；未声称运行时性能或完整发布门禁通过。
