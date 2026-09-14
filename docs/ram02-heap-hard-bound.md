# RAM-02：堆硬边界与失败契约

2026-09-13，对应 `build/quality-audit-20260912/REPORT.md` RAM-02。
代码侧越界保护已完成，实机堆峰值和整个运行时 RAM 安全尚未验收。
原始审计报告保留不改。

## 根因与修复

原 `_sbrk` 只比较 `_estack`，允许突破 1024 B 预留，也允许负增量退入
静态数据区；先计算越界指针还存在 C 指针运算问题。

- `ldscript/n32l406.ld`：保留 `_Min_Heap_Size=0x400`，在预留尾部导出
  `_heap_limit`，增加容量与最低栈预留不重叠断言。没有释放这 1024 B。
- `src/syscalls.c`：有效 break 区间为 `[_end, _heap_limit]`，已分配内存
  为 `[_end, break)`。先用无符号地址距离检查，再推进或回退 break。
  处理零增量、负增量、`INT_MIN/INT_MAX`；拒绝时返回 `(void *)-1`、设置
  `errno=ENOMEM`，保持 break 不变。成功返回旧 break，不擅自清除 errno。
- `include/syscalls.h`：记录失败契约与使用限制。分配仅限主上下文，未增加
  ISR 分配支持、锁或中断屏蔽。
- `tools/tests/test_heap_bounds.py`：编译真实 `syscalls.c`；只替换链接器地址
  并隔离主机 CRT 同名 syscall，验证上下界、极值、失败恢复、重复耗尽/回收、
  非对齐增量及 RAM 哨兵不被修改。没有用 Python 模型代替实际 C 实现。

固定堆边界保护未来向下增长的栈空间，比仅比较当前 SP 更稳定；它不能阻止
栈自身越过边界。`_Min_Stack_Size=2048` 仍仅为链接最低预留，不是栈安全证明。
没有移除 libc、替换格式化函数或把堆归零。

## 格式化与观测边界

本轮扫描 `src/*.c` 未见直接 malloc/calloc/realloc/free、printf/fprintf/
sprintf/asprintf/vasprintf 调用。libc 格式化调用是 snprintf/vsnprintf，
分布在 EC800M、FOTA、JT808 参数、平台日志和 F39 回复；dbg_printf 是项目自身
实现。当前 ELF 仍保留 `_malloc_r`、`_realloc_r`、`__ssputs_r`。

当前工具链把 snprintf 与 sniprintf、vsnprintf 与 vsniprintf 放在相同地址。
反汇编中 sniprintf 初始化 FILE 标志为 `0x208`；__ssputs_r 的动态增长路径
检查 `0x480`，两者按位与为零。因此不能根据该函数含 malloc 分支便断言普通
固定缓冲 snprintf 会分配。分配失败路径可见 ENOMEM 和错误返回；这属于静态
调用证据，不是目标 newlib 的完整动态故障注入验证。

既有 HEALTH 日志的 HEAP_USED 来自 sys_heap_break，是采样时当前 break 用量，
不是历史高水位，也不是 malloc 净载荷。此次未增加常驻 RAM 计数器。
堆回退后旧堆内容还可能影响染色扫描，不能仅凭一次 STK_PEAK 宣称真实栈上限。

## 本轮验证

本机 make 不在 PATH，以下 make 实际为
`D:/A300_Tools/toolchains/make-4.4.1/bin/make.exe`。

| 命令 | 结果 |
|---|---|
| `python tools/tests/test_heap_bounds.py` | 原代码 upper/lower/mixed 均因越界未拒绝而失败；修复后三组通过 |
| `python tools/tests/test_ram_watermark.py` | PASS |
| `python tools/tests/test_f39_end_to_end.py` | PASS，主机回复回归，不等于目标 newlib 测试 |
| `python tools/tests/test_feature_guards.py` | PASS |
| `make -B all BUILD=build/ram02-20260913` | PASS；编译/链接未见 warning/error；Flash gate 提示余量低及配置变化 |
| `make release-guard` | PASS，仅版本/发布输入校验 |
| `python tools/libc_parser_guard.py build/ram02-20260913/a300_firmware.map` | PASS |
| `make ram-guard BUILD=build/ram02-20260913` | FAIL，保留 RAM-01 阻断：3772 B 小于要求的 4096 B，栈证据仍不完整 |
| `git diff --check` | PASS，只有 Git 换行转换提示 |

产物隔离在 `build/ram02-20260913/`；构建日志 `build/ram02-build.log`，
RAM gate 日志 `build/ram02-ram-guard.log`。未覆盖发布固件或修改版本头。

最终 MAP/ELF：静态 `.data + .bss = 17820 B`，与审计相同；
`_end=0x2000459c`、`_heap_limit=0x2000499c`、`_estack=0x20006000`。
堆硬容量 1024 B，堆上界至 RAM 顶端 5732 B。Flash 105808/106496 B，
剩余 688 B；较审计 105776 B 增加 32 B。Flash gate 标记配置不可直接比较，
因此该数字是相对审计的差值，不宣称是严格受控性能实验。
最终 LTO `_sbrk` 单帧 16 B；已知主循环调用帧链仍为 2984 B。

## 尚需验收

需要实机/HIL 验证：冷启动首次格式化、最长 F39 回复、最大 HTTP/AT 请求、
反复通信及 OTA、STOP2 唤醒后的堆/栈观测；调试构建中记录每次 _sbrk 的
break 与失败事件以获取真实峰值，并验证目标 newlib 分配耗尽后的调用方恢复。
不得把测试固件的故障注入带入生产，也不得在 ISR 中调用分配函数。
本轮没有实机、烧录或部署，未执行完整发布 gate；其 RAM 前置检查已明确失败。
RAM-02 的代码边界缺陷已修复，HIL 验收未关闭；RAM-01 和 Flash 低余量仍是
独立风险。已有用户修改保持原样，未提交或推送。
