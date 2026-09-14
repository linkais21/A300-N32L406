# 静置挂测复位修复与 DUP-02 SHA 共用

2026-09-13。用户授权先修复 EC800M 接收边界，再独立评估 App 内 SHA 共用。
本轮完成代码、host 回归及 ARM 构建；**未进行实机/HIL，RAM/release-gate 仍失败**。
没有提交、推送、烧录、部署或生成新的正式版本包。现有 V3.038/V3.039 归档未改动。

## 现场证据与根因边界

COM4 2026-09-13 挂测日志显示 V3.038 两次 IWDG 复位（原日志第 6342、6568 行），
第二次保留 `phase=ec800m fault=0`。日志没有复位瞬间的 DMA 剩余计数，不能把
已复现的软件缺陷直接认定为两次实机复位的唯一原因。

原 `drain_rx`、AT response、prompt、QIRD 的写指针是 `1024 - DMA剩余计数`，
剩余计数为零时得到 1024，而消费指针通过 `%1024` 始终处于 0..1023，循环无法结束。
连接失败清理路径还会把同一越界值赋给消费指针。

新增 host 测试编译实际 `src/ec800m.c`，用硬件替身注入该边界。原实现五个路径均
超过 3 秒，测试子进程被有界超时终止；修复后五个路径通过。

## 接收修复

`rx_write_position()` 是所有 DMA 写指针读取的统一入口：零和重载容量均转换为零索引；
异常的大于容量的计数保持当前消费位置，不访问不可信索引。每个消费 pass 保持固定快照。
不改 UART/DMA 通道、remap、缓冲容量、AT ownership、超时或看门狗配置。

测试包含空/重载、异常计数、恰好在环尾结束及跨环的 URC/OK/ERROR/prompt、二进制
QIRD（含 NUL/CR/LF）、超时释放 owner、失败连接清理，以及 10,000 次环尾交替采样。
现有 URC、QISEND、身份恢复、注册、NTP、GPS wait service 和 reset diagnostics 回归通过。
这不解决 DMA 整环覆盖导致的空/满歧义，也不宣称已证明持续输入时的最坏服务间隔。

## DUP-02 实现

新增 `include/sha256.h`、`src/sha256.c`。从原 App FOTA 实现提取增量 SHA-256 核心，
替换 FOTA 和 AGNSS 各自的私有 SHA 实现。使用 64 位位数累计，更新前提升长度为 64 位。
FOTA 与 AGNSS 继续各自使用局部 context；不新增全局工作区、堆分配或跨模块锁。

包 SHA、AGNSS payload SHA、CRC、签名、metadata/commit marker、读会话失效及 Flash
owner 均保留。Bootloader 保持独立实现和独立链接。新增源文件加入 Makefile 和相关
host C 编译入口。旧 `build_all.ps1` 为已知过时入口，缺少新源文件，不能用于本轮产物。

SHA 验证将实际 C 输出与 Python hashlib 比较：空消息、abc、55/56/63/64/65 字节
填充边界、127/128/129、4,097、105,808、155,392 和 1,000,000 字节，各种分块长度、
零长度更新和双 context 交错处理，共 181 个摘要。旧 FOTA 核心与共享核心分别通过。
另外执行实际 OTA 流程的包哈希/CRC/签名入口拒绝测试、AGNSS 快照/NOR 断电切点、
真实平台签名及篡改拒绝测试。

## 同一工作树分阶段构建结果

| 阶段 | App BIN | Flash 剩余 | 静态 RAM | 已知调用链栈帧和 | 扣静态/已知栈后余量 |
|---|---:|---:|---:|---:|---:|
| 本轮输入 baseline | 105,776 B | 720 B | 17,904 B | 2,984 B | 3,688 B |
| 仅接收修复 rx-fixed | 105,800 B | 696 B | 17,896 B | 2,984 B | 3,696 B |
| 再共用 SHA sha-shared | 105,160 B | 1,336 B | 17,896 B | 2,984 B | 3,696 B |

接收修复增加 24 B；SHA 共用单独节省 640 B；本轮合计净节省 616 B。
静态 RAM 减少的 8 B 未对应到 RAM 对象大小缩减，按实际链接布局变化记录，
不声称删掉了某个缓冲。SHA 共用本身未改变静态 RAM。

三个构建使用相同编译器、编译/链接参数。SHA 阶段新增源文件，因此配置指纹的
源列表变化是有意的；基线与接收阶段配置指纹相同。三阶段日志均未发现编译器
warning/error。Flash guard 通过，但保留 LOW_HEADROOM；相对历史冻结 profile
仍有 CONFIGURATION_CHANGED 提示，未改阈值或冻结基线。

三个 RAM gate 均失败。最终 3,696 B 小于要求的 4,096 B，且仍有 91 个缺失栈帧、
56 个间接跳转等未闭合证据；不能声称整体 RAM 安全。SHA core 的 256 B 消息调度数组
仍为局部栈，未改成共享全局缓冲。距离 4 KiB Flash 余量目标还差 2,760 B。

## 执行与证据

构建根目录 `build/stability-sha-20260913/`：

- `before-source/`：开始时四个生产输入文件；保留用户已有优化，不从 HEAD 回滚。
- `baseline/`、`rx-fixed/`、`sha-shared/`：各阶段 ELF/MAP/BIN、Flash 报告和栈证据。
- `comparison.json`：三阶段 BIN 大小、余量、SHA-256。
- `rx-red.log`：旧驱动五条路径超时的 RED 证据。
- `rx-regression.log`：13 个接收/GPS/reset 相关脚本通过。
- `sha-regression.log`、`sha-test-results.json`：22 个相关脚本通过。
- `*-stack.log`、`*-ram.log`、`release-gate.log`：保留资源阻断结果。

主要命令（在固件仓库执行）：

```powershell
python tools/tests/test_ec800m_dma_wrap.py
python tools/tests/test_sha256_shared.py --legacy-source build/stability-sha-20260913/before-source/src/fota.c
python tools/tests/test_sha256_shared.py
python -m pytest -q -p no:cacheprovider tools/tests/test_agnss_snapshot.py tools/tests/test_agnss_scheduler.py tools/tests/test_agnss_storage.py tools/tests/test_fota_platform_flow.py tools/tests/test_fota_resume.py tools/tests/test_fota_checkpoint_powercut.py tools/tests/test_ext_flash_store_host.py tools/tests/test_ext_flash_layout.py tools/tests/test_feature_guards.py
python tools/tests/test_build_dependencies.py
python tools/tests/test_flash_gate_build.py
python tools/release_guard.py
python tools/libc_parser_guard.py build/stability-sha-20260913/sha-shared/a300_firmware.map
& ../tools/w64devkit/w64devkit/bin/make.exe -j4 all BUILD=build/stability-sha-20260913/sha-shared
& ../tools/w64devkit/w64devkit/bin/make.exe release-gate BUILD=build/stability-sha-20260913/sha-shared
git diff --check
```

定向 pytest：24 passed；构建依赖和 Flash 门禁构建测试通过；release identity 和
libc parser 检查通过。release-gate 在 RAM 阶段退出 2，未放宽、删除或绕过校验。
独立代码审查未发现本轮引入的阻断性缺陷，并独立复跑 DMA 和 SHA 测试通过。

## 本轮实际文件范围

生产修改：`src/ec800m.c`、`src/fota.c`、`src/agnss_storage.c`、Makefile；新增
`src/sha256.c`、`include/sha256.h`。保留其上已有的 PERF-02/构建改动。

新增测试：`tools/tests/test_ec800m_dma_wrap.py`、`tools/tests/test_sha256_shared.py`。
更新 SHA 链接输入：`test_agnss_snapshot.py`、`test_ext_flash_store_host.py`、
`test_fota_checkpoint_powercut.py`、`test_fota_modem_handoff.py`、`test_fota_platform_flow.py`。
文档：本文件、实施计划及 README 入口。

## 后续实机/HIL

上述 BIN 是保持当前工作树版本标识的工程对照产物，不是新的版本化烧录交付物。
不能替换已有 V3.039 归档或将同版本不同内容包混用于 OTA。

下一次挂测应首先使用仅接收修复的独立版本候选，与旧日志区分构建身份；保持相同
供电、天线、主备平台和上报周期，至少覆盖原约 3 小时触发区间，建议连续 24 小时。
记录每次复位原因/阶段、RAM_GAP/STK_PEAK/HEAP_USED、GPS DROP、通信失败和最长服务间隔。
没有 IWDG 复位只能证明本次场景，不能替代 DMA 零/重载瞬间和持续 RX 压力验证。

接收修复挂测稳定后，再验证 SHA 共用候选的 OTA 合法/坏哈希/坏签名、断点恢复及
AGNSS 真实注入。当前仍需要实机/HIL 验证，不关闭现场复位与 RAM 验收项。
