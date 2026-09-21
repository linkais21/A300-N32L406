# 最近优化复审与 V3.048 稳定性测试交付

2026-09-15，用户要求重新审核近期优化、修复后生成一版供手动烧录挂测。
交付目录：`artifacts/HIL-STABILITY-20260915-V3048/`。
版本 `T360-A300_406_20260823000000,V3.048`，计数 3048，MCU N32L406CBL7。

## 审查结论

本轮为范围内自审，不宣称独立评审或实机验收。

| 项目 | 复核结果 |
|---|---|
| DUP-01 OTA 活动查询 | 保留 READY 调度让步、一次状态读取、未知状态行为；状态枚举和调用者回归通过 |
| DUP-02 App SHA | 已共享核心，独立上下文；181 个摘要通过，FOTA/AGNSS/签名回归通过；Boot 独立实现 |
| PERF-04 OTA 单次扫描 | 最小包确保首块包含完整 header，CRC/SHA 范围及拒绝顺序正确，失败诊断重新初始化 CRC；扫描预算回归通过 |
| RAM-03 工作区 | 不合并具有重叠生命周期的缓冲；确认配置查询调用者存在下述缺陷并修复 |
| RAM-04 RX 字段重排 | 仅内部 RAM 布局，无持久化/协议 ABI 变化；双通道边界与换代回归通过 |
| debug UART 统计 | 保留有界同步发送；新增真实 C 测试覆盖可发、等待、超时、清零及恢复。wait_cycles 是轮询次数，不是 CPU 周期；当前没有串口输出消费者，不声称已测出时延 |

## 本轮修复

`src/cfg_query.c` 的旧实现在 UDP pending 后释放 DIAGNOSTIC owner，导致其他使用者
可覆盖仍被事务引用的 RX；启动被拒绝又不释放 owner，持续 busy；TX 引用调用栈上的
16 B 请求，生命周期不覆盖后续 process。确认报文改变类型后还沿用旧校验和。

修复将 TX 放在既有 service 工作区尾部 16 B，RX 容量改为 1008 B，两者不重叠；
pending 保留 owner，结束后才释放，启动拒绝返回失败并释放。请求及 ID 在事务启动时
冻结，确认报文重新计算 XOR。活动事务期间 `cfg_query_init` 不取消或丢弃事务，继续
通过 process 完成；头文件说明此契约。没有增加静态 RAM、修改 Flash 布局或取消签名校验。

`test_cfg_query_lifetime.py` 编译生产查询与工作区源码，覆盖 owner 竞争、栈扰动、
填满 RX 而不破坏 TX、pending、多次 init/start、启动拒绝、无效 ID、坏响应、事务失败、
正常确认及完成后重新启动。旧实现正常/坏响应/事务失败场景被 pending 所有权断言拒绝，
启动拒绝场景被 busy 断言拒绝（exit 1）；修复后 5 场景通过。
TX 生命周期另由代码数据流核对支持，不将所有分支都声称为独立 RED 证据。

边界：当前生产 `ec800m_udp_txn` 只完成发送并返回发送状态，尚未实现完整 UDP 应答接收；
本轮没有扩展该协议，正常确认路径在 host 注入应答验证。启动失败不再无限挂起，
但 `main` 每次启动只发起一次查询，不新增自动重试策略。无需该查询成功才能完成挂测。

## 验证与构建

```powershell
python build/review_stability_3048.py tests
python tools/tests/test_debug_uart_stats.py
python build/review_stability_3048.py build
git diff --check
```

- 第一条逐个运行 49 个脚本，均退出 0（列表及各自日志在 validation 中），不是 49 个 pytest 用例；混合实际 C、模型和静态契约测试。
- 新增 UART 实际 C 测试单独通过；查询 RED→GREEN、SHA 181 摘要、真实签名、FOTA 续传/掉电及 Boot 恢复均有定向证据。
- 构建脚本使用当前 Makefile，在独立 `build/stability-review-3048/app` 和 `boot` 全量构建；App/Boot 编译成功，无编译器 warning/error。
- 版本契约、release-guard、平台信任锚、必要帧预算、libc、Flash 容量、Boot 静态容量、manifest、包 CRC/长度/版本/向量、Combined 工厂标记及 HEX→BIN 一致性检查通过。
- 完整 `make release-gate` 退出 2：RAM 门禁拒绝，90 个缺失栈帧、56 个间接转移、117 个尾转移和 1 个循环，完整栈/堆/异常上界未证明。未更改阈值或豁免正式发布检查。
- `git diff --check` 通过；原工作树存在 LF/CRLF 提示。

最终 App BIN 105184 B，容量 106496 B，剩余 1312 B；保留 LOW_HEADROOM、CONFIGURATION_CHANGED。
静态 RAM 17896 B，已知调用帧和 2520 B，扣除两者后余 4160 B，尚未扣未知堆/IRQ 等。
Boot 静态容量检查通过，不代表 Boot 运行栈已验证。资源数字不是本轮各优化独立收益。

## 交付与风险

沿用既有工程 HIL 交付路径，manifest 明确 `release_approved=false`。这是用户要求的
手动烧录稳定性测试包，不是正式量产放行。正式 `tools/build_dev_release.py` 门禁保持原样。
ZIP 包含 Combined HEX/BIN、OTA BIN、说明和校验值；目录另含 ELF/MAP、日志和源码快照。
Combined 首次启动清理配置 A/B、BCR、OTA checkpoint 和 authorization；先记录需恢复配置。

需要实机/HIL 验证：冷启动、双通道鉴权/重连、AGNSS/OTA 切换、Flash/Boot 跳转与恢复、
24 小时静态挂测的复位原因、STK_PEAK/RAM_GAP、HEAP_USED、GNSS QDROP/CS/OREF 及最大服务间隔。
历史 V3.047 已出现 RAM_GAP=3904、F=1 和持续 QDROP，本轮不声称消除了这两个问题；
没有修改 GNSS 模块配置、里程阈值或扩大队列，相关根因仍需专门测量。
未烧录、上传平台、部署、提交或推送。

本轮修改：`src/cfg_query.c`、`include/cfg_query.h`、`release_identity.json`、
`include/config.h`、`include/build_version.h`、`tools/release_guard.py`（仅版本文件指纹）、
`tools/tests/test_release_identity_contract.py`、本说明、RAM-03 后续状态及 README 交付入口。
新增 `tools/tests/test_cfg_query_lifetime.py`、`tools/tests/test_debug_uart_stats.py`、实施计划、
本次 build 脚本和独立产物。其余用户已有优化作为最终构建输入保留。
