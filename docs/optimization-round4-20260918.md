# 第四轮保持功能优化：栈证据补全（2026-09-18）

本轮承接第三轮建议，优先修正最终链接栈分析。完成尾转移后继补全及入口可达缺口报告；尚未建立全程序 RAM 上限，发布门禁仍不通过。固件源码、功能、日志、版本、编译参数、Flash 布局及交付包均未改变。

## 本轮文件

- `tools/stack_usage_guard.py`：原分析器只列出跨函数尾转移，没有遍历其后继。本轮增加包含直接调用和尾转移的 `call_edges`，保留原 `direct_edges` 字段；保守相加调用者与被调用者已知帧，不假定尾跳转已释放调用者栈。偏移入口按所属符号继续追踪，但仍列为未证明尾转移。新增 main、启动和中断入口的 `root_gaps`，列出静态可达的缺失帧、间接转移、尾转移和环。
- `tools/tests/test_stack_tail_evidence.py`：5 个回归覆盖尾链后继、条件偏移跳转、局部跳转与独立 IRQ、缺失目标、纯尾转移环。
- `docs/superpowers/plans/2026-09-18-preserve-features-round4.md` 和本文：范围、结果及后续工作。

所有未知项仍阻止 `complete` 成立；`map_ram_guard.py` 没有改变。帧和省略未知帧，遇到环也不构成有限上限；可达清单不包含未知间接目标，因此不是完整运行调用图。未实现通用 ARM 控制流/栈解释器，不将反汇编启发式结果视为证明。

## 同一最终 ELF 的前后比较

ARM GNU 14.3.rel1，当前 Makefile，固定版本头；本轮 BIN 与第三轮最终 BIN 逐字节一致。

| 项目 | 修改前分析器 | 修改后分析器 |
|---|---:|---:|
| App Flash / BIN | 106292 B | 106292 B |
| App 分区余量 | 204 B | 204 B |
| 静态 RAM（map guard） | 17716 B | 17716 B |
| main 已知帧和 | 2536 B | 2536 B |
| 全局缺失帧 / 间接转移 / 尾转移 / 环 | 73 / 56 / 131 / 1 | 73 / 56 / 131 / 1 |

108 个函数入口的已知帧和改变。例如 `fota_on_chunk` 从 248 B 增至 1196 B，`fota_ec800m_rx` 从 216 B 增至 1228 B。它们是分析补全导致的诊断变化，不是固件栈用量增加。main 已知最长路径仍为 FOTA 验签到 micro-ecc，但间接调用可能隐藏其他更深路径。

## 已核对证据及缺口

1. **main 可达缺口**：394 个静态可达函数、55 个缺失帧、48 个间接转移、94 个未证明尾转移，且可达一个调用环。大部分缺失帧来自 newlib/libgcc，包括格式化、内存/字符串、浮点辅助函数；还包括 `gpio_af_rx`。不能对库函数填入零帧，也不能直接借用相似函数的 `.su`。
2. **间接转移分类**：全局 56 项中有 14 条 `ldr ... pc, [sp]`，是返回指令候选；仍需验证对应保存/恢复路径，未从未知项中删除。其余包括寄存器调用、回调及跳表。micro-ecc 的函数指针和 modem/F39 回调需要绑定最终目标集合；仅有直接路径的 2536 B 不能覆盖它们。
3. **环**：新增尾边后诊断路径经 `at_send_wait -> at_send_wait_owned -> process_rx_byte -> process_rx_line -> process_urc -> at_send_wait` 回环。源码存在 AT owner 及 `s_deferred_urc_processing` 防重入条件，但本轮没有证明所有路径上的状态约束，不删除环、不宣称实机无限递归。
4. **堆**：当前链接 `_end=0x20004538`、`_heap_limit=0x20004938`，保留 1024 B；`src/syscalls.c` 的 `_sbrk` 上下界及 INT_MIN/INT_MAX、失败不改变 break、重复申请/释放 host 回归通过。该证据证明分配接口边界，不代表堆峰值或整体运行安全。计入静态区末尾对齐后，24576 − 17720 − 1024 − 2536 = 3296 B，尚须承担未知调用帧、中断/异常和余量，不能称为已证明的安全余量。
5. **中断**：源码 `hw_init.c` 配置 priority group 2；UART4/DMA5 为抢占优先级 1，TIM8 为 2；`main.c` 的 USART1 为 3；`work_mode_sleep.c` 的唤醒 EXTI 为 1、RTC 为 2。工具已按入口单列缺口，但没有合成嵌套上限。SysTick、异常、硬件压栈、FPU lazy stacking、对齐、启动残留帧及运行期优先级状态仍需完整核对。零已知帧不表示硬件压栈为零。

## 验证

在仓库根目录使用 `../tools/w64devkit/w64devkit/bin/make.exe`：

```text
make BUILD=build/optimization-round4-20260918/final -o include/build_version.h all
make BUILD=build/optimization-round4-20260918/final -o include/build_version.h release-gate
```

- 构建退出 0，Flash guard 通过，仍提示 LOW_HEADROOM。容量工具相对其既有基线另报 CONFIGURATION_CHANGED；本轮与第三轮的逐字节比较不依赖该工具基线。
- 新增 5 项测试对修改前分析器为 4 FAIL + 1 ERROR（缺少新增 `root_gaps` 字段），对最终分析器为 5 PASS。尾链帧和实际复现为 24 B 而非期望 152 B；修正后为 152 B，提供 RED→GREEN 证据。
- 以下 9 项 `python tools/tests/test_<name>.py` 均退出 0：`stack_tail_evidence`、`lto_stack_guard`、`ram_guard`、`heap_bounds`、`ram_watermark`、`stack_health_observability`、`fota_stack_guard`、`feature_guards`、`platform_trust_anchor`。
- `test_ram01_frame_budget.py <final-build>`、libc parser guard 和范围内差异检查通过。采用 requesting-code-review 的小改动自审方式检查调用图字段兼容、未知项保留及测试边界。
- **完整 release-gate 退出 2**：release-guard 通过后 ram-guard 拒绝不完整栈证据；没有降低门禁。main 已知帧扣除后 4324 B 的诊断值仍未计堆、中断及未知帧。

证据位于 `build/optimization-round4-20260918/`：输入/最终哈希、分析器起始快照、构建日志、逐项命令及退出码 `results.json`、同一 ELF 的旧分析器结果 `before-analysis.json`、对比 `comparison.json`、最终 ELF/map/.su/分析报告及按符号大小排序的清单。`verify.py` 可重跑回归和对比。哈希确认已有输入仅改变 `tools/stack_usage_guard.py`；新增测试/文档另列于本报告。

需要实机/HIL 验证：冷启动、OTA 验签与 modem 回调叠加时的栈水位，中断嵌套和低功耗唤醒。没有提交、推送、部署、烧录或覆盖交付固件。

## 是否还有第五轮

**有，建议继续，优先收敛全程序 RAM 证据。**

1. 先绑定 modem/F39/micro-ecc 回调目标以及跳表，验证 AT owner/防重入条件对环的约束；必须用最终 ELF 身份和拒绝路径测试约束证据，不能手工豁免。
2. 补齐 newlib/libgcc 和缺失应用帧，验证尾转移及返回路径；再将堆硬边界、启动和中断/异常上限合并成可审计预算。
3. Flash 仍仅 204 B 余量。如果继续体积优化，应从本轮最终符号清单重筛重复实现，例如较大的命令解析/配置分发，先做真实 C 等价回归再测量。符号大不代表可安全删除，尤其不能为省空间跳过盲区掉电恢复或 OTA 校验。本轮没有承诺第五轮节省量或门禁必然通过。
