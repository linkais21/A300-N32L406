# N32L406CBL7 最终迁移、Bootloader 与 App 产物设计

## 1. 目标与冻结基线

本轮把 `A300-first` 完整收口到 **N32L406CBL7**，并生成可追溯的 Bootloader 与 App 开发签名产物。当前工作区资料中出现的 `N32L406CDL7 / 384 KiB` 属于旧型号信息，不得进入本轮链接、容量检查或发布元数据。

冻结硬件容量为：

- 内部 Flash：128 KiB，地址 `0x08000000–0x0801FFFF`。
- SRAM：24 KiB，地址 `0x20000000–0x20005FFF`。
- 系统时钟：64 MHz。
- 外部 Flash：BY25Q16ESMIG，现有分区与 owner 仲裁保持不变。

内部 Flash 最终分区为：

| 区域 | 起始地址 | 结束地址 | 容量 |
|---|---:|---:|---:|
| Bootloader | `0x08000000` | `0x08005FFF` | 24 KiB |
| App | `0x08006000` | `0x0801FFFF` | 104 KiB |

选择 24 KiB Bootloader 是为了容纳经过验证的软件 ECDSA P-256 验签及安全启动平台代码；不采用原 11 KiB 发布上限，也不以仅 SHA 校验或自制简化密码算法换取空间。

## 2. 实施范围与顺序

实施按以下依赖顺序推进：

1. 修正目标型号、内部 Flash 分区、链接脚本、容量守卫和 App 向量表迁移。
2. 完成 Bootloader 的 N32L406 平台层及真实安全启动路径。
3. 建立本地开发密钥、签名打包和 `DEV-KEY` 产物流程。
4. 完成 App 侧验签复用与 BCR/manifest 契约一致性。
5. 完成 STOP2、复位诊断和唤醒后外设恢复。
6. 关闭盲区存储复审确认的两个状态机根因，并保留掉电事务语义。
7. 运行全量 host 回归、ARM 构建、map/容量门禁并生成 Bootloader/App 产物与校验清单。

Zhongkewei 二进制 envelope 保持 fail-closed。没有厂商协议或真实抓包时不得臆造兼容行为；它作为外部验证门禁记录，不阻止已支持路径的开发构建，但阻止将整机宣称为生产发布就绪。实机/HIL 与 72 小时耐久测试同样属于外部发布门禁。

## 3. Bootloader 架构

### 3.1 平台层

新增独立的 N32L406 Bootloader 平台实现，替换当前默认失败的 weak hooks，负责：

- 初始化系统时钟、SPI1/BY25Q16、内部 Flash、看门狗和最小诊断能力。
- 对外部 Flash 执行有界 read/program/sector erase、完成性检查和 read-back。
- 对内部 App 区执行页/字编程、擦除、读取及边界保护。
- 提供复位原因、单调回滚计数、系统复位以及安全 App 跳转。
- 跳转前关闭中断与 SysTick、恢复必要时钟状态，校验 MSP 位于 SRAM、Reset_Handler 位于 App 区，设置 MSP 与 VTOR 后跳转。

所有擦写和校验循环必须有上限并持续服务看门狗。任何地址越界、manifest 不一致、哈希或签名失败均 fail-closed，进入有界恢复路径，不跳入未知镜像。

### 3.2 安全启动与镜像事务

Bootloader 只持有公钥并只执行验签，不包含私钥，也不再为 LKG 现场签名。镜像格式保持固定 manifest，签名覆盖明确的规范化数据：manifest 中不可变身份/地址/长度/版本字段与 payload SHA-256；CRC 用于发现 manifest 存储损坏，ECDSA P-256 用于真实性验证。

安装流程为：验证外部 signed package → 备份已经通过验证的 signed package 为 LKG → 分块复制 candidate 到 App → 逐块 read-back → 校验内部 App hash → 原子提交 BCR Trial → 跳转。Trial 超限后只恢复此前已验证且签名仍完整的 LKG；LKG 不可用时尝试已签名 Factory；均失败则留在恢复模式。

BCR 双槽写入遵守 erase、record write、read-back、最后 commit marker 的掉电安全顺序。Bootloader 和 App 共用同一份状态、地址和 manifest 契约，禁止复制漂移的常量。

## 4. App 迁移

App 链接起点改为 `0x08006000`，最大 104 KiB，SRAM 保持 24 KiB。链接脚本必须为向量表、代码、只读数据和 `.data` 装载地址提供正确映射，并在链接期拒绝越过 `0x08020000`。

App 启动早期显式把 VTOR 设置为 `0x08006000`，该动作发生在启用业务中断之前。App 侧 FOTA 使用与 Bootloader 相同的 P-256 公钥和签名输入规范，下载完成后先验证 package，再提交 BCR Pending；不能依赖当前 weak verifier 的默认失败实现，也不能绕过签名验证。

容量门禁更新为 App 104 KiB、Bootloader 24 KiB、SRAM 24 KiB；map 报告同时保留合理栈余量。若真实代码超限，先通过可审查的尺寸优化收口，不改变安全模型。

## 5. 开发密钥与产物

当前没有生产私钥。本轮生成一把 ECDSA P-256 开发密钥：

- 私钥只存放在仓库内被忽略的 `.keys/`，不得提交、打印或复制到产物目录。
- 公钥以可复现的生成文件嵌入 Bootloader 和 App 验证端。
- 构建/签名脚本拒绝缺失或格式错误的密钥，输出签名 package 及 manifest 检查报告。
- Bootloader、App、组合/升级包、清单和文件名全部明确标记 `DEV-KEY`，不得标记为 production-ready。
- 交付清单包含目标型号、地址、长度、版本计数、SHA-256、签名状态、构建工具版本和 Git/dirty 状态。

后续替换生产密钥只允许替换受信公钥及受控签名输入，不改变镜像协议或降低验证规则。

## 6. STOP2 与复位诊断

深度睡眠改用 N32L406 的 STOP2 能力。进入前保存必要上下文，配置并清理唤醒源，停止不允许跨 STOP2 保持的外设；唤醒后恢复 64 MHz 时钟、tick、GPIO/AF、UART、SPI/I2C 与业务外设，再恢复 GPS/EC800M 状态机。

STOP2 前置条件不满足或配置失败时使用明确的浅睡眠 fallback，不假装进入 STOP2。新增复位诊断模块采集并清理 RCC/PWR 复位原因，向启动逻辑提供 brownout/watchdog/software 等分类，同时用有界、脱敏日志暴露原因。STOP2 和复位诊断不得在 ISR 内执行复杂恢复。

## 7. 盲区状态机 Fix Round 3

只修复复审确认的两个确定性无进展循环：

1. repair 将 `PREPARED` 记录备份并恢复后，验证阶段必须接受语义仍合法的 `PREPARED`，不能只接受 `ACTIVE` 而永久重试。
2. 整环回卷遇到 next slot 上的 stale `ACTIVE` 时，reconcile 必须通过有界、幂等的回收/推进规则取得进展，不能反复观察同一槽位。

修复保持 NOR 1→0、sector erase、scratch repair、FIFO 与掉电恢复不变量。测试先稳定复现两个循环，再覆盖 repair 各掉电切点、整环、重启、重复 reconcile、sequence wrap 和最终进展断言。其余已关闭开放项不在本轮扩展。

## 8. 错误处理与安全边界

- 密码校验、地址/MSP/入口校验、内部 Flash read-back 或 BCR 提交失败时不启动新镜像。
- 外部 Flash 操作失败、超时或 owner 冲突时返回可恢复状态，不无限重试。
- 恢复链严格为当前有效 App、LKG、Factory、恢复模式；每个候选都必须重新验签。
- 开发私钥永不进入源码、日志、Git 或 Bootloader。
- 不覆盖工作树中已有的用户修改；重叠文件只做任务所需的最小 hunk。
- 不自动烧录、部署或发送真实设备控制命令。

## 9. 验证与验收

自动验证至少包括：

- 盲区两个失败用例的 RED→GREEN 与全部 `tools/tests/test_*.py` 回归。
- BCR、manifest、FOTA package/resume、external Flash layout/store、release guard 和 feature guard。
- 使用指定 ARM GNU 14.3 工具链 fresh 构建 Bootloader 与 App，生成 ELF/HEX/BIN/map。
- 链接地址、VTOR、App 向量 MSP/Reset_Handler、Bootloader/App 边界、SRAM 和栈余量检查。
- 使用开发私钥签名，再由嵌入公钥离线验签；篡改 payload、manifest、签名及回滚版本均必须拒绝。
- `git diff --check`、产物哈希清单及敏感文件扫描，确认 `.keys/` 未跟踪。

最终可交付状态是“**N32L406CBL7 开发签名构建完成**”，并提供 Bootloader 与 App 的 `DEV-KEY` 产物。只有板上验证通过 Bootloader 跳转、candidate 安装、断电恢复、Trial/LKG/Factory 回滚、STOP2 各唤醒源、看门狗/brownout，以及 Zhongkewei 厂商流验证和 72 小时混合负载测试后，才能升级为生产发布就绪。

