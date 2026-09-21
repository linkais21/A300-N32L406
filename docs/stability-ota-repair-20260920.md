# 稳定性、OTA 与资源修复验证记录

2026-09-19 开始，2026-09-20 汇总。依据工作区 `outputs/firmware-quality-audit-20260919/企业级代码质量与资源优化诊断.md`，目标为当前 N32L406 固件工作树。未提交、推送、烧录或部署。

## 结论与发布边界

完成三项可复现故障修复及资源去重；76 个相关 host 测试脚本通过，App/Bootloader 构建通过。**RAM guard、release-gate 仍失败，不具备发布验收结论。** 剩余 App Flash 1,492 B，仍低于 4 KiB 预警线，不能称为已解决容量不足。

报告没有证实内存泄漏或已经发生栈溢出。当前业务源码未发现 malloc/calloc/realloc/free 调用，但 libc 格式化仍存在分配路径；保留 1 KiB 堆硬边界并运行 heap 边界测试，不据此宣称无泄漏。HardFault 现场读取、IRQ/FPU 嵌套和最坏运行时栈尚缺实机证据。本轮不改引脚、型号、升级鉴权契约或 Flash 布局；审核指出的资料冲突继续保留。

## 按优先级修复

| 项目 | 根因、修改及现有功能影响 | 验证 |
|---|---|---|
| 持续喂狗的等待无法退出 | EC800M 的 AT response、prompt、QIRD、残留清理及 alive probe 只依赖 tick 超时。冻结 tick 时持续喂狗会使等待永不结束。每次等待增加独立的停滞计数，正常 tick 仍使用原超时；保留 owner、服务回调及清理路径 | 新测试修复前 7 个场景全部超时；修复后有界返回、释放 AT owner，后续正常响应可用；DMA wrap、URC 重入、TCP/UDP、短信、注册和发送恢复回归通过 |
| If-Range 无法安全重下 | 已有断点的请求收到 HTTP 200 + 新 ETag 时，在进入原有归零事务前被拒绝。只允许完整 200 更新 ETag，仍拒绝 206 混合内容；先提交零断点再擦候选区 | 修复前无法进入 PREPARING；修复后零断点/CRC/ETag 正确，提交后立即重启也从零安全重下；Range、碎片、断网、日志逐字节掉电回归通过 |
| 续装跳过已提交前缀检查 | Bootloader 仅验证本次写入页，断电前已提交前缀损坏时仍可能进入 TRIAL。在 TRIAL 提交前复用现有缓冲区核对整个内部镜像与已验签候选；失败返回现有回滚路径 | 修复前 4 个损坏/读失败场景错误进入 TRIAL；修复后拒绝且允许读故障恢复后重试。生产 C 安装器+BCR：2,048/2,049/4,097 B 镜像穷举 870 切点；106,496 B 最大镜像另测 353 切点，共 1,223。含部分擦除/写入、marker 和最终回读 |
| Q04 无效通道副本 | EC800M 私有通道对象只保留被读取的 state，删除从未读取的 IP/port 复制；保留公共 typedef、generation、QIRD mask、UDP transaction、上层重连状态 | 对象从 304 B 变为 4 B；网络和 modem 测试通过，含主/备连接、stale URC、异常 owner/重入 |
| Q05 SMS/F39 栈压力与重复代码 | 删除 SMS 的 256 B 中间回复副本，保留异步 retry 副本；合并发送失败分支并在回调前固定原 handoff 策略。配置事务移入私有 noinline 函数；成功回复在事务函数返回后格式化 | SMS、F39 查询/配置/失败/回调/RESET/RELAY/ACK 顺序等回归通过；最终 LTO 帧见下表。业务处理顺序、回复内容、权限和持久事务保留 |
| OTA 重复扫描代码 | 完整包扫描与失败诊断的 body 扫描共用 helper；SHA 上下文和 256 B 读缓冲在调用验签前退出栈。保留一次正常扫描、独立向量读取和全部失败诊断 | 生产 SHA/CRC、读取次数、最大包、边界尺寸、失败顺序、真实平台签名和错误签名拒绝均通过 |

安装掉电测试使用真实 `image_install.c`、`bcr.c`、`image_verify.c` 及符合 NOR 1→0/sector erase 的模型；该掉电夹具中的 ECC 边界为 stub，不能冒充真签名测试。真实 ECC/平台信任锚由独立签名回归覆盖。Python Boot 模型的最大镜像穷举测试亦通过，但与生产 C 证据分别记账。

既有双槽 checkpoint、完整包 SHA-256/ECDSA、型号/版本/长度/CRC/向量校验、Pending/Trial、Factory/LKG 回滚均保留。网络重试仍有次数上限，耗尽后保留断点供下一次检查或重启恢复；没有引入无限重试。

## 同配置资源结果

对比本轮开始前的实际工作树，不以 Git HEAD 或旧审核快照替代。当前起点已包含其他工作完成的 Q03 JT808 字段清理，本轮没有改动 `jt808.c`，不重复计入其收益。

| 指标 | 本轮起点 | 最终 | 差异 |
|---|---:|---:|---:|
| App BIN/Flash span | 104,996 B | 105,004 B | +8 B（含全部可靠性修复） |
| App Flash 剩余 | 1,500 B | 1,492 B | -8 B，LOW_HEADROOM 保留 |
| 静态 RAM（map） | 17,584 B | 17,280 B | -304 B，其中通道对象 -300 B，另有布局对齐变化 |
| SMS 执行最终栈帧 | 832 B | 576 B | -256 B |
| F39 公共入口最终栈帧 | 1,160 B | 56 B | 大事务移至独立函数；配置路径仍有 1,160 B 事务帧，不能当全程序节省 1,104 B |
| OTA 验签入口最终栈帧 | 528 B | 128 B | -400 B；扫描 helper 独立帧 408 B，与 ECC 路径分离 |

最终静态分析已知主调用链帧和 2,536 B；扣静态 RAM 和该帧和后为 4,760 B，**尚未扣除 heap、未知帧及 IRQ/FPU，不能称作运行时安全余量**。68 个 missing frame、66 个 indirect transfer、133 个 tail transfer、2 个 internal call、1 个 cycle 仍待闭合。

去重基本抵消加固开销，但没有取得 App 净 Flash 缩减。未改变优化等级、日志等级、密码算法、有效缓冲区大小和功能开关来换取数字。

## 实际验证

证据目录：工作区 `outputs/stability-ota-repair-20260919/`。

- `regressions.json`：76 个相关 host 脚本最终退出码均为 0；包括新增四个测试、既有 checkpoint 逐字节掉电、LKG promotion、Boot recovery、真实签名、网络、短信、F39、盲区、heap、Flash owner 和布局回归。
- App：工作区 make 工具执行 `-B -o include/build_version.h all BUILD=../outputs/stability-ota-repair-20260919/reviewed-build`，退出 0。使用现有工具链、Makefile 参数及版本头，未刷新版本时间戳。Flash guard、release identity、libc parser、必要帧预算测试通过；构建无 `warning:`。
- Boot：在只读输入快照的 `source/bootloader` 下执行 `make -B all TOOLCHAIN_ROOT=<原仓库/.toolchain/bin>`，退出 0；text 14,512 B、data 4 B、bss 3 B。静态容量 gate 通过，Boot 运行时栈仍未完整审计。
- `gates-final.json`：RAM guard/release-gate 退出 2，原因是完整运行时栈证据未证明；未改动门禁阈值或 fail-closed 行为。
- 验证过程的已解决问题：首次调用 `test_ram01_frame_budget.py` 漏传构建目录；补传最终目录后通过。新增掉电测试的计数局部变量触发 longjmp clobber 编译告警，改为静态测试计数后通过。Boot 首次解析工具链 junction 到非 ASCII 路径失败，改用原有 ASCII junction 路径后构建通过。这些不记为固件缺陷。
- 最终检查：本轮范围 `git diff --check` 通过，仅 Git 既有 LF/CRLF 提示。源输入 SHA-256、原始修改前文件和本轮增量 diff 保存在证据目录。
- 按 requesting-code-review 做本轮范围自审：核对调用者、资源释放、CRC skip 下界、callback 生命周期、掉电事务和失败路径；未执行独立人员审查。

## 实际触碰文件

生产源码：`src/ec800m.c`、`src/fota.c`、`src/at_config.c`、`src/f39_reply.c`、`bootloader/src/image_install.c`。

新增测试：`tools/tests/test_ec800m_stalled_tick.py`、`test_fota_if_range_restart.py`、`test_boot_resume_integrity.py`、`test_boot_install_powercut_c.py`。

新增文档：本记录和 `docs/superpowers/plans/2026-09-19-stability-ota-repair.md`。另新增上述证据目录中的快照、独立构建、测试 runner、日志及哈希；未覆盖正式 firmware/artifacts 产物，保留所有无关既有工作树修改。

## 仍需完成

1. **需要实机/HIL 验证**：tick 故障时 watchdog/恢复时序；长时间联网和弱网/断网续传；GNSS+双路 JT808+OTA 并发时 UART/DMA 水位。
2. **需要实机/HIL 验证**：下载 checkpoint、内部页/BCR、Trial/LKG promotion 各阶段真实断电；错误签名/损坏包拒绝；看门狗/异常重启回滚；恢复镜像的实际 provision 状态。主机测试不保证任意硬件损坏下绝不变砖。
3. **需要实机/HIL 验证及静态证据补全**：最大 SMS/F39、验签、STOP 唤醒、IRQ/FPU 和故障捕获时栈/heap 水位；完整 RAM 发布门禁未闭合。
4. Flash 仍低于 4 KiB 预警线。后续优化需有具体无读者或等价证据，不能通过删签名、回滚、业务功能或有效缓存达标。
