# 第九轮：0x8105 复位与栈转移漏报修复（2026-09-19）

完成本轮三项修复和主机验证：0x8105/04 终端复位、R8-01 条件调用漏报、R8-02 CBZ/CBNZ 跨函数转移漏报。独立固件构建通过；完整发布门禁仍失败，不能作为已验证发布包。进入本轮时，第八轮记录的源文件哈希全部一致，既有工作树改动保留。

## 终端复位契约

- 已鉴权会话收到消息号 `0x8105`、消息体恰好为单字节 `04`，复用 F39 `RESET`。
- 先在请求通道尝试发送 `0x0001` 通用应答：原请求流水号、应答消息号 `0x8105`、结果 `00`。保留请求终端标识；成功表示命令已接受，不表示物理复位已完成。
- 应答发送尝试返回后安排 100 ms 延迟，主循环 `at_config_process()` 到期调用 `NVIC_SystemReset()`；没有收包栈内直接复位或新增等待循环。实际复位时间还受主循环调度影响。
- 应答发送失败仍安排复位，不等待平台确认。重复请求合并，保持第一次已安排的截止时间，不允许反复下发无限推迟复位。该规则也适用于共享默认执行器的串口/短信 RESET。
- 空消息体或多余字节返回结果 `02`，其他未支持控制字返回 `03`；原有 `64/65` 继电器安全策略不变。未鉴权、失效会话和校验失败帧不执行复位。

修改 `src/jt808.c`：文本命令和复位共用带消息号的应答回调，保留原有 ACK 在破坏性动作前的顺序。修改 `src/at_config.c`：已有复位截止时间不被重复请求覆盖。

新增 `tools/tests/test_terminal_reset.py`：链接真实 JT808、会话、at_config、F39 解析和执行模块，仅用桩替代外设/传输。覆盖主备通道、流水号/消息号/终端标识、鉴权、半包、校验失败、长度错误、不支持命令、发送失败、重复请求、计时回绕及会话代际失效。发送桩中推进时间并运行主循环，确认首次 ACK 尝试期间未提前安排复位；到期仅执行一次。

## 栈分析器修复

修改 `tools/stack_usage_guard.py`，新增 `tools/tests/test_stack_conditional_transfers.py`（7 个测试方法，含子用例）：

- 按 BL/BLX/BX 指令类别和条件后缀识别转移。条件调用保留可能执行的调用边；条件寄存器调用/跳转仍是未解决项。`ble`、`blt`、`bls` 等 Bcc 不会被当作 BL。
- CBZ/CBNZ 跨函数目标进入保守尾转移图，目标的缺失帧和间接转移传播到调用根；局部比较分支不增加尾转移。
- 直接调用函数内部地址保留原始 `direct_edges` 目标，并在 `call_edges` 中跟踪所属函数的后继。新增顶层及 `root_gaps` 下的 `internal_calls` 字段（caller、target、instruction），阻止 `complete=true`。所属函数入口帧不构成内部入口栈状态证明；局部子程序不直接等同于完整函数递归。
- 不放宽机器码帧证明、运行预算或发布拒绝规则。

真实 ARM 汇编器/objdump 夹具确认条件直接调用的 8+128 B 已知帧和不再漏报，条件寄存器转移保留未知项，CBZ/CBNZ 目标的 128 B 帧及后继缺口可达。最终固件中两处 `bleq` 内部入口现在明确出现在 main 的 `internal_calls`：`__aeabi_dmul+0x1dc`、`__aeabi_ddiv+0x16e`。这关闭的是漏报，不是这两条路径的栈证明义务。

## 实际验证

执行 `python build/optimization-round9-20260919/verify.py`，后续 `--resume` 仅复用输入不变的记录并补跑独立 stack-guard。每条命令、退出码在同目录 `results.json`，最终输入在 `final-input-hashes.json`；修改前源码在 `before/`，本轮源码差异在 `round9.patch`。

- **RED→GREEN**：最终测试在隔离的修改前源码上复现失败。`red-stack.log` 为转移漏报，`red-reset.log` 为应答结果非成功，`red-deadline.log` 为仅补协议入口但保留旧调度器时重复请求推迟截止时间。没有回滚工作树。当前实现对应测试通过。
- **18 个回归脚本退出 0**：terminal_reset、remote_relay、jt808_text_command、text_ack_order、at_config_serial_f39、at_config_handoff、jt808_dual_session、f39_actions、sms_execute_boundary、sms_ingress、stack_conditional_transfers、stack_machine_frames、stack_table_targets、stack_indirect_evidence、stack_tail_evidence、lto_stack_guard、ram_guard、feature_guards。
- **环境问题记录**：首次 at_config_handoff 因默认 w64devkit GCC 未启用 LTO 失败。改用已安装 WinLibs GCC 16.1.0 后，最终全部主机回归重新执行通过，未更改测试或取消 LTO。首轮结果及失败日志保留于 `first-verification/`。
- **构建退出 0**：ARM GNU 14.3.rel1，现有 Makefile，`BUILD=build/optimization-round9-20260919/final`，`-o include/build_version.h` 固定已有版本头，`make -j4 all`。没有分配新发布版本或覆盖交付包。
- **发布失败仍保留**：release-gate 退出 2，第一项失败为 RAM guard 的 `incomplete stack evidence`；release-guard 已通过。独立 stack-guard 也退出 2；独立 platform-trust-guard、flash-guard 和必要帧预算测试通过。验证脚本预期该失败仅为继续收集证据，其退出 0 不表示发布成功。
- 最终机器码帧证据及跳表字节均与 BIN 核对一致；本轮源码 `git diff --check` 通过。范围自审核对了应答先于调度、失效会话拒绝、计时回绕、重复请求以及内部调用缺口传播；未使用独立代理审查。

| 指标 | 第八轮 | 第九轮 |
|---|---:|---:|
| App BIN | 106376 B | 106444 B |
| App 分区余量 | 120 B | 52 B |
| 静态 RAM | 17716 B | 17716 B |
| main 已知帧和（非最坏上限） | 2536 B | 2536 B |
| 缺失帧 / main 可达缺失帧 | 68 / 52 | 68 / 52 |
| 间接转移 / 尾转移 / 调用环 | 67 / 130 / 1 | 67 / 130 / 1 |
| 显式内部调用缺口 | 未单列，条件调用漏报 | 2 |

本轮增加 68 B，Flash 仍有 LOW_HEADROOM、CONFIGURATION_CHANGED 告警。`process_frame` 帧维持 232 B；共用命令处理辅助函数由原文本辅助函数的 24 B 增至 32 B，main 已知最长路径数值不变。剩余 4324 B 仍未扣除完整堆/IRQ/未知路径，不能宣布 RAM 安全。

BIN SHA256：`c5d3e6b0c351722d06a443ae3d20b8dc93f9c8c0d7dab209d8a43ec6afd9e196`。

ELF SHA256：`c041ff27cfda9263fc835ba1c50609a9f4821636e6eb494f397c9cd1cec0d644`。

## 实机验收与后续

**需要实机/HIL 验证**：主/备平台下发 0x8105/04，抓取对应 0x0001 应答，观察 MCU 复位原因/启动日志及重连鉴权；再验证重复下发、应答丢失和低功耗状态下的恢复。主机测试不能证明网络送达或硬件复位。本轮没有烧录、发送真实设备控制命令、提交或部署。

第九轮限定修复已完成。若继续第十轮，应处理实际缺失库帧、内部入口、回调及堆/IRQ 预算证明，并关注仅 52 B 的 Flash 余量；不能把本轮漏报修复视为发布收尾。

本轮实际触碰：上述 3 个实现文件、2 个新增测试、本文、`docs/superpowers/plans/2026-09-19-preserve-features-round9.md`，以及 `build/optimization-round9-20260919/` 下本轮证据和独立构建文件。
