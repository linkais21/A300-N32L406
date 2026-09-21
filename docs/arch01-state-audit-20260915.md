# ARCH-01 第一阶段：恢复步骤与事务可审计化

范围：`src/blind_zone.c`、`src/agnss_storage.c`、`src/agnss_manager.c`。
以 2026-09-15 当前工作树为基线，保留已有 V3.048 修改。原审计报告的
Flash/RAM 数字及 AGNSS 实现属于历史基线，不代替本轮测量。

## 执行计划与验收

1. 在 `build/arch01-20260915/before` 全量构建当前源码，保存三个源文件快照，运行现有真实 C/NOR 回归。
2. 将盲区恢复的每个既有分支提取为文件内步骤函数；入口只负责抢锁、单步分派和解锁。
3. 展开 AGNSS 单行存储事务和调度代码，标出校验、元数据发布及失败清理边界。
4. 运行同组回归、布局/owner 检查和构建 gate；比较 BIN、静态 RAM、最终 LTO 栈报告；审查逐状态副作用顺序。

验收：接口、状态枚举、NOR 格式、提交顺序、重试/预算、返回结果保持不变；
不新增静态 RAM，不改全局编译/内联参数；阶段函数用 `always_inline` 明确源码拆分边界，
以本轮 BIN 和最终 LTO 栈一致性验证其没有增加调用开销。没有功能缺陷修复，因此使用
现有行为回归和前后等价证据，不人为制造 RED。若暴露覆盖缺口，再补有意义的测试。

## 盲区恢复契约

入口在 IDLE/READY 时立即返回；其他状态使用非等待式 BLIND_ZONE owner 抢锁。
抢锁失败不推进状态。每次调用只执行进入时的一个分支，状态变化下次调用才分派。
步骤函数名称以 `_locked` 结尾，不自行释放入口取得的锁。
循环预算仍为 `BZ_RECOVERY_READS`（16），它限制扫描迭代，不代表最多 16 次底层 I/O：
部分迭代包含写入/复读，阶段结束还有原有维护操作。

下表省略 `BZ_RECOVERY_` 前缀；I/O 失败若未特别说明则保持进度并计数重试。

| 状态 | 主要副作用及后继 |
|---|---|
| SCRATCH_CHECK | 读取 scratch 头；空白→META，有效→SCRATCH_VALIDATE，无效→SCRATCH_DISCARD |
| SCRATCH_VALIDATE | 分块验证备份记录及 CRC；坏记录→DISCARD；扫描完→SCRATCH_VICTIM_VALIDATE |
| SCRATCH_VICTIM_VALIDATE | 对照原扇区 CRC；备份有效→REPAIR_VICTIM_ERASE，仅原扇区有效→DISCARD，两者无效→IDLE |
| SCRATCH_DISCARD | 擦除 scratch，成功→META |
| META | 扫描日志，选择 generation 最新有效元数据；有效/空白→DATA，只有旧格式→IDLE |
| DATA | 扫描数据/损坏记录；完成后修复、RECONCILE 或原始扫描收尾 |
| RECONCILE | 补提交 PREPARED，收养未入日志记录；处理 rollover、陈旧满环记录和维护收尾 |
| FINALIZE | 提交恢复元数据；成功后维护收尾，日志满转 rollover |
| CLEANUP | 对不在逻辑队列的有效记录写 CONSUMED，完成后维护收尾 |
| CONSUME | 对 peek 快照目标写 CONSUMED，全部完成→CONSUME_META |
| CONSUME_META | 提交消费后队列元数据；成功置完成标记，否则 pending/error |
| ROLLOVER_SCAN | 按待提交队列清理陈旧记录；完成→ROLLOVER_ERASE |
| ROLLOVER_ERASE | 擦元数据日志，写待提交状态，成功才应用 RAM 状态并恢复维护/消费/reconcile |
| REPAIR_BEGIN_ERASE | 擦 scratch，重置备份游标→REPAIR_BACKUP |
| REPAIR_BACKUP | 按原槽位备份需保留记录；完成→REPAIR_HEADER，写失败→BEGIN_ERASE |
| REPAIR_HEADER | 写 scratch 头及最后提交 marker；成功→REPAIR_VALIDATE，失败→BEGIN_ERASE |
| REPAIR_VALIDATE | 复读备份并验证 CRC；成功→VICTIM_ERASE，无效→BEGIN_ERASE |
| REPAIR_VICTIM_ERASE | 擦原扇区；成功→REPAIR_RESTORE |
| REPAIR_RESTORE | 按 bitmap 恢复精确槽位；完成→REPAIR_VERIFY，写失败→VICTIM_ERASE |
| REPAIR_VERIFY | 比较备份/原扇区，必要时补交 PREPARED；完成→FINAL_ERASE，比较失败→VICTIM_ERASE |
| REPAIR_FINAL_ERASE | 擦 scratch 后清修复标记；启动恢复→META，否则隔离缺失队首并恢复原维护阶段 |

## AGNSS 接口与副作用

| 接口/阶段 | 所有权、发布及失败契约 |
|---|---|
| begin | 先关闭读快照；获得 Flash owner 后擦目标槽；成功持锁供 write/commit，擦失败解锁 |
| write | 先关闭快照；活动事务、指针和容量检查；验证写成功才推进位置；失败 abort |
| commit | 校验长度，获得 service workspace；复读 payload 算 CRC/SHA；擦元数据、写正文、最后写 marker；成功释放两种 owner 并更新 latest；失败释放 workspace 后 abort |
| get_latest | 分别读取两个槽元数据并解锁；逐槽校验 payload；保持既有无符号 sequence 比较（含回绕时的原行为） |
| read/open/chunk | 保留 legacy 每次全量验证和新快照接口的区别；chunk 校验固定槽元数据身份，失败关闭快照 |
| abort/close | 关闭读快照；abort 仅在活动写事务时释放 Flash owner |
| process | OTA/模组/GPS/刷新/重试门控；每轮至多一块或一次结束回调；成功才推进偏移或完成标记；失败关闭快照并设置 60 秒重试期限 |

## 后续范围与硬件验证

`main.c:work_mode_process` 和 `ec800m.c:qird_collect_payload` 暂未修改，
ARCH-01 不应标记整体关闭。它们需要各自的策略/串口回放和状态副作用表。
本轮目标不是节省 Flash 或提高速度。恢复期间主循环/IRQ 延迟、真实掉电和
AGNSS 串口注入仍需要实机/HIL 验证；不发布、打版本包或烧录。

## 完成结果与评审

第一阶段已实现。`blind_zone_recovery_process` 从 555 行缩为 50 行，21 个阶段
函数保留各自的原分支语句和顺序。AGNSS 两个文件去掉空白/注释后的 token 序列
与工作树快照一致。没有修改协议、Flash 布局、状态枚举或对外接口。

本轮实际触碰：三个范围内 C 文件、`tools/tests/test_blind_zone_store.py`、本文档，
以及忽略目录 `build/arch01-20260915/` 下的基线快照、构建和验证证据。
`agnss_manager.c` 原有修改保留；其他已有修改和版本/固件发布产物未改。

自查覆盖了 21 个状态分派映射、分支语句等价性、入口抢锁/解锁、局部预算重置、
NOR 正文/marker 发布顺序、错误退出及 owner 释放。未调用独立审查代理。
新增真实 C 测试覆盖抢锁失败、单步转移、读失败解锁、16 次扫描预算和 READY 幂等；
重构前快照与最终源码均通过，将预算改为 17 的临时变体被预算断言拒绝。

| 证据 | 重构前基线 | 最终结果 |
|---|---:|---:|
| App BIN | 105,184 B | 105,184 B，逐字节相同 |
| App 分区余量 | 1,312 B | 1,312 B |
| 静态 RAM（.data + .bss） | 17,896 B | 17,896 B |
| main LTO 栈帧 | 392 B | 392 B |
| blind_zone_recovery_process.part.0 栈帧 | 184 B | 184 B |
| 全部最终 LTO 栈帧 | 316 条 | 去除路径/行号后全部相同 |
| 已知主调用链栈帧小计 | 2,520 B | 2,520 B，非完整栈上界 |

共同 BIN SHA-256：`6e00b1ff6bbe5abfe00d4ea9e82144b3d8c5c5fbf1223f0e1c82b689c5d737eb`。
不承诺节省空间、性能提升或未来其他工具链也产生相同机器码。

最终证据使用 `baseline/` 和 `final/`；`baseline.mk` 仅在分析目录将三个编辑文件的
编译输入指向修改前快照，其他构建输入使用当前 Makefile。`before/`、`after/`、
`after-inline/` 为过程产物，不作为最终对照证据。

## 执行命令及结果

当前 shell 的 PATH 未包含 make；使用项目发布脚本同样支持的本地可执行文件
`../tools/w64devkit/w64devkit/bin/make.exe`，以下记为 make。所有命令在固件仓库运行。

| 命令 | 结果/日志（均在 build/arch01-20260915 下） |
|---|---|
| `make -f Makefile -f build/arch01-20260915/baseline.mk all BUILD=build/arch01-20260915/baseline` | 通过；baseline-build.log |
| `make all BUILD=build/arch01-20260915/final` | 通过；final-build.log；Flash guard 通过，保留低余量警告 |
| `python build/arch01-20260915/check_equivalence.py` | 通过；equivalence.json/log：token、分支、BIN、栈比较和预算变体拒绝 |
| `make release-guard` | 通过；release-guard.log；不是完整 release-gate |
| `make -f Makefile -f build/arch01-20260915/baseline.mk ram-guard BUILD=build/arch01-20260915/baseline` | 失败，原有完整栈证据缺失；baseline-ram-guard.log |
| `make ram-guard BUILD=build/arch01-20260915/final` | 同样失败，原因和已知栈数据相同；final-ram-guard.log |
| `git diff --check` | 通过；Git 提示未来检出时 LF/CRLF 转换，无空白错误 |

以下 10 个脚本均使用 `python tools/tests/<文件名>` 直接执行并检查各自退出码，全部返回 0；
结果见 `final-tests.log`。直接执行很重要：部分脚本仅有 `main()`，pytest 收集计数不能证明其运行。

- `test_blind_zone_store.py`（34 个 C 测试场景，含原有逐阶段掉电/部分写入、容量、回绕和修复回归）
- `test_blind_zone_replay.py`（含 ACK 流水号变体拒绝）
- `test_agnss_snapshot.py`（真实存储/调度代码、NOR 一向写、元数据逐字节切点、CRC/SHA/owner/边界）
- `test_agnss_scheduler.py`
- `test_agnss_workspace_ownership.py`
- `test_agnss_vendor_stream.py`
- `test_agnss_storage.py`（辅助模型测试，不单独作为设备行为证明）
- `test_ext_flash_store_host.py`
- `test_ext_flash_layout.py`
- `test_feature_guards.py`

RAM gate 仍报告 90 个缺失栈帧、56 个间接跳转、117 个尾跳转和 1 个环，无法证明
整个程序的栈/堆/异常上界。本轮没有解决 RAM-01，也不能声称完整发布验收通过。
未执行生产部署、烧录或实机/HIL；后续仍需完成前述硬件验证和 ARCH-01 其余两个模块。
