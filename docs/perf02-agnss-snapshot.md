# PERF-02：AGNSS 分块读取验证快照

日期：2026-09-13。对应 `build/quality-audit-20260912/REPORT.md` 的 PERF-02。
代码优化和 host 验证完成；**RAM/release-gate 未通过，不代表可以发布**。

## 行为与边界

- 新增 `agnss_storage_read_open/read_chunk/read_close`。首次 open 沿用原有双槽
  metadata CRC、commit marker、payload CRC32/SHA-256 验证和选择策略，保存完整
  64 字节元数据及槽号。重复 open 返回固定快照，不重复全包扫描。
- read_chunk 持有 AGNSS Flash owner 时重新读取并逐字节比较该槽元数据，再读取
  指定块；保留 workspace owner、长度、offset、防溢出和错误返回。所有 owner
  在返回前释放，不跨主循环占用 Flash；OTA 调度优先级不变。
- init、begin（包括失败）、write、commit、abort、显式 close 使快照失效；
  读块失败、管理器类型不匹配或回调失败也关闭会话。写事务中不能打开读会话。
  init 通过 abort 释放正在进行的本模块写事务，不释放其他 owner。
- 注入完成后关闭会话并将 offset 归零；后续两小时刷新重新验证、从头注入。
  管理器换包检测增加 payload CRC，覆盖序号/长度相同但内容变化的情况。
  失败重试保留原有 offset 语义和 60 秒退避。
- 原有 `get_latest/read` 仍进行独立完整验证。持久化布局、元数据格式、
  CRC/SHA 算法、最后提交 marker、数值型 sequence 排序不变。

约束：单主循环调用；AGNSS 区域写入必须经过本存储模块，禁止其他模块直接改写。
一次会话中的 payload 不再每块全量复核，因此会话建立后、元数据不变的自发
Flash bit flip 不保证在当前会话中发现；下一次会话会完整拒绝损坏数据。
元数据变化和底层读取报错在当前块拒绝。该快照策略不提供逐块持久化哈希。
第一次打开仍是同步全包扫描，本轮仅消除重复扫描，不声称消除了长步骤停顿。

## 可重复证据

`tools/tests/test_agnss_snapshot.py` 编译实际 storage、manager、ext_flash_store、
service_workspace、crc32 C 文件，模拟 NOR 1→0 和 4 KiB 擦除，逐字节核对注入输出。
I/O 计数仅包含 payload，另有每次打开的双槽元数据读取、每块 64 B 元数据比较。

| 输入 | 优化前 payload 读取 | 优化后实测 | 校验/读取预算 |
|---|---:|---:|---|
| 单槽 4,097 B，5 块 | 49,164 B（RED 实测） | 8,194 B | 2L |
| 双槽各 4,097 B | 未记录旧实现实测 | 12,291 B | 3L |
| 单槽最大 155,392 B | 未运行旧最大输入 | 310,784 B | 2L |
| 单槽空 payload | 未记录 | 0 B | 仍验证空 payload 哈希和元数据 |

4,097 B 用例 payload I/O 减少 83.33%，这是 host 读取量，不是 CPU/实机耗时加速比。
RED 断言为 `payload_reads <= 2 * length`，旧实现失败，新实现通过。
另覆盖双槽回退、CRC/SHA 损坏拒绝（修正 CRC 后仍拒绝坏 SHA）、边界/零长/
重复随机块读、序号 wrap 保持原数值排序、OTA/workspace 争用且不解锁其他 owner、
metadata/payload 读取失败、擦除失败、部分 payload 写入、64 字节 metadata/marker
所有写入切点（0..64）、初始化/中止/换槽失效、相同序号长度换包、中途及完成
回调失败、下一会话重新验证和两小时刷新。

## 构建与资源

使用当前 Makefile 和已有用户改动，工具链及优化参数不变。
最终对照为 `build/perf02-20260913/baseline/` 与 `after/`。对照构建通过
`build/perf02-rebuild-baseline.py` 仅从 HEAD 恢复本轮原先干净的两个 AGNSS C 文件
到临时源码目录，用 Makefile overlay 编译为原对象路径，不回滚工作树。
对照 BIN 与修改前首次构建的 hash 一致；两产物 configuration_sha256 相同。
早期 `before/` 后被 make 依赖更新重建，**不用于最终资源对照**。

| 指标 | 修改前 baseline | 修改后 after | 差值 |
|---|---:|---:|---:|
| App BIN | 105,792 B | 105,776 B | −16 B |
| App 分区剩余 | 704 B | 720 B | +16 B |
| 静态 RAM | 17,820 B | 17,904 B | +84 B |
| 已知最大 main 调用链栈帧和 | 2,984 B | 2,984 B | 0 B |
| 扣静态 RAM/已知栈后的余量 | 3,772 B | 3,688 B | −84 B |

两份构建/Flash guard 通过，无编译 warning/error。Flash guard 保留
LOW_HEADROOM/CONFIGURATION_CHANGED 告警：历史审计 profile 与当前配置不同；
本轮前后配置相同，可以互相比对。

基线 BIN SHA256：`612c0ae42d1bd55eeafc03c86a17abda8498bd8895cd0c89f80b0fd322aced90`。
优化 BIN SHA256：`0c34036a59cc00ed656cf8b91db98b06adc9b569571ccc301af37aed6b0f4f9b`。

`ram-guard` 两份均失败：已知调用链为 main → fota_process → checkpoint_save →
newest → ext_flash_read → spi_flash_read → ready → read_status_command；两份余量
均低于 4,096 B，尚未计堆/异常及未知栈。最终报告仍有 91 个缺失帧、56 个间接
跳转等未闭合证据。不能把旧 18,040 B 静态阈值当作运行安全证明；本轮增加的
84 B 状态会进一步消耗余量。本轮没有放宽门禁，也不处理其他审计项。

## 执行命令和结果

在固件仓库执行：

```powershell
python tools/tests/test_agnss_snapshot.py
python -m pytest -q -p no:cacheprovider tools/tests/test_agnss_snapshot.py tools/tests/test_agnss_storage.py tools/tests/test_agnss_scheduler.py tools/tests/test_ext_flash_store_host.py tools/tests/test_ext_flash_layout.py tools/tests/test_feature_guards.py
python tools/tests/test_agnss_workspace_ownership.py
python tools/tests/test_agnss_vendor_stream.py
python tools/tests/test_zhongkewei_agnss.py
& ../tools/w64devkit/w64devkit/bin/make.exe -j4 all BUILD=build/perf02-20260913/after
& ../tools/w64devkit/w64devkit/bin/make.exe release-gate BUILD=build/perf02-20260913/after
python tools/libc_parser_guard.py build/perf02-20260913/after/a300_firmware.map
python tools/tests/test_platform_trust_anchor.py
git diff --check
```

pytest：16 passed；三个独立脚本通过；完整构建通过；release identity、libc parser、
真实平台签名/篡改拒绝通过。release-gate 在 RAM 阶段失败，后两项单独执行验证。
日志：`build/perf02-tests.log`、`perf02-after.log`、`perf02-gates.log`、
`perf02-baseline.log`、`perf02-baseline-ram.log`。独立审查无阻断性发现；补齐了
审查建议的同序号换包和晚期回调失败用例。

## 需要实机/HIL 验证

未烧录、部署、签名打包或运行设备控制。需要实机/HIL 验证：GNSS 两种厂家流的
真实输出、SPI 读取量/时序、DWT 周期、主循环 worst gap、并发 UART RX 压力、
实际 Flash 失败/断电恢复，以及 HEAP_USED/STK_PEAK/RAM_GAP。未提供 IRQ 最坏
延迟或运行栈上界证明。原始审计 REPORT.md 保持只读。

本轮修改：`include/agnss_storage.h`、`src/agnss_storage.c`、`src/agnss_manager.c`、
`tools/tests/test_agnss_scheduler.py`；新增快照测试、本说明及
`docs/superpowers/plans/2026-09-13-perf02-agnss-snapshot.md`。其余已有用户修改保留，
未提交、推送或覆盖发布目录。
