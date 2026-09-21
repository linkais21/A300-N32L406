# DUP-01：共享 OTA 活动状态查询

2026-09-15，对应 `build/quality-audit-20260912/REPORT.md` 的 DUP-01。
本项完成源码维护性收敛，Flash/RAM 收益均为 0 B；不代表发布验收完成。

## 修改范围和契约

- `include/fota.h`：新增轻量 `static inline bool fota_is_active(void)`，一次读取状态。
- `src/agnss_manager.c`、`src/agnss_huada.c`：删除各自的重复谓词，调用共享查询。
- `src/tcp_manager.c`：既有 `tcp_manager_ota_active()` 保留为兼容包装。
- `tools/tests/test_fota_active.py`：遍历全部 9 个枚举状态，检查非法值及单次读取；新增枚举时要求明确测试预期。
- `tools/tests/test_tcp_identity_gate.py`、`tools/tests/test_agnss_vendor_stream.py`：去掉复制的 FOTA 头文件桩，直接使用生产头文件。

CHECK_CONNECTING、CHECKING、PREPARING、CONNECTING、DOWNLOADING、VERIFYING、READY 返回真；
IDLE、ERROR 和未识别值返回假，与原实现一致。READY 在等待复位期间继续阻止 AGNSS 和 TCP 抢占。
查询表示调度让步条件，不替代外部 Flash owner 锁。协议、状态枚举数值和持久化格式不变。
GPIO TX/RX 命名保留；SHA 和月份表不在本次修改范围。
用户已有 FOTA、JT808、工作区所有权等未提交修改保留，作为本轮前后构建的共同输入。

## 构建与二进制证据

使用当前 Makefile、ARM GCC 14.3.1、默认完整功能和 LTO，分别在新目录全量构建：

```powershell
mingw32-make all BUILD=build/dup01-20260915/before
mingw32-make all BUILD=build/dup01-20260915/after
```

两个命令均成功，日志位于 `build/dup01-before-build.log`、`build/dup01-after-build.log`。
首次尝试 `make` 因 PATH 无该命令而未启动，随后使用已安装的 `mingw32-make`。
没有运行会修改版本号的发布脚本，没有覆盖已有交付固件。

| 度量 | 修改前 | 修改后 |
|---|---:|---:|
| BIN | 105128 B | 105128 B |
| App 余量 | 1368 B | 1368 B |
| .data | 296 B | 296 B |
| .bss | 17600 B | 17600 B |
| 静态 RAM | 17896 B | 17896 B |

Python 直接比较两份 BIN，结果完全相同；SHA-256 均为
`31459510a5cfe0dc7cd90ec32f1bb18edf10abd5e92febd3d819458a84dca361`。
`arm-none-eabi-size -A` 确认前后节区大小和地址一致。
`arm-none-eabi-nm -S`：修改前三个 OTA 谓词均为 `0x0800788c / 32 B`；
修改后三个 `fota_is_active.lto_priv.*` 仍为该地址和尺寸。
GPIO TX/RX 前后均为 `0x08008196 / 34 B`。
20260912 报告中的地址和容量是历史基线，不作为本次增量收益。

## 自动验证

新增查询测试在实现前因缺少 `fota_is_active` 编译失败，实现后通过；这是新 API 的 RED→GREEN，原有逻辑没有已知行为缺陷。
以下脚本使用 `python tools/tests/<文件名>.py` 执行，全部通过：

- test_fota_active
- test_agnss_scheduler
- test_agnss_snapshot
- test_tcp_manager_fip
- test_tcp_identity_gate
- test_shallow_sleep_contract
- test_agnss_workspace_ownership

`python -m pytest -q -p no:cacheprovider tools/tests/test_agnss_vendor_stream.py tools/tests/test_agnss_workspace_ownership.py`
结果 1 passed；workspace 脚本另按独立入口运行，不把 pytest 收集当作它的执行证据。
此前一次 pytest 命令误列不存在的 `test_agnss_fota_lockout.py`，未运行任何测试；修正后按上述真实入口验证。

`mingw32-make release-guard ram-guard BUILD=build/dup01-20260915/after`：
release-guard PASS；ram-guard FAIL，日志为 `build/dup01-gates.log`。
栈报告已知调用帧和为 2520 B，缺失帧 90、间接转移 56、尾调用 117、循环 1；
全程序栈/堆/异常边界证据不完整，不能通过 RAM 发布验收。
Flash guard PASS，但仍有 LOW_HEADROOM 和相对历史基线的 CONFIGURATION_CHANGED 提示。
`git diff --check` 通过。

## 验证边界

BIN 相同支持本次默认配置的机器码等价，不宣称全配置等价、运行时栈安全或延迟改善。
未执行实机、烧录、升级、部署或完整发布流水线；OTA/AGNSS/TCP 并发调度及主循环/IRQ 延迟需要实机/HIL 验证。
未提交、推送；版本号不变。
