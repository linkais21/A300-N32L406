# Combined 烧录后一次性出厂初始化设计

## 目标

生产环境每次通过 SWD 烧录 `Combined-N32L406CBL7.bin` 后，Bootloader 在跳转
App 前自动完成一次选择性外部 Flash 初始化。正常重启、仅 App SWD 烧录和 OTA
升级不得重复清理。整个过程必须可掉电重试且无需烧录完成后再次使用 SWD 调试器。

本设计解决已复现的故障：内部 Bootloader 与 App 完整有效，但外部 Flash 的 BCR
槽包含非 BCR 遗留数据，`bcr_load()` 返回 `BCR_LOAD_INVALID`，Bootloader 因
fail-closed 策略停留在 recovery loop，App 无串口输出且 EC800M 未初始化。

## 约束与非目标

- 只修改 Bootloader、发布/生产烧录脚本、测试和相关文档。
- 不修改 App 核心业务、JT808、GNSS、EC800M 或 FOTA 运行逻辑。
- 保留 Bootloader 对真实 BCR 撕裂或损坏的 fail-closed 行为。
- 不擦除 Factory、LKG、OTA candidate、盲区和 AGNSS 区域。
- 不把 FOTA HTTP 鉴权纳入本次启动修复。配置恢复默认值后，空
  `device_api_key` 导致的 HTTP 401 作为生产自检警告；JT808 ONLINE 是联网通过
  条件。
- 生产烧录仍使用 SWD 写入 Combined 镜像，但烧录后的初始化和启动不得依赖后续
  SWD 命令。

## 方案选择

采用“内部一次性请求标志 + Bootloader 选择性初始化”。不采用以下方案：

- 不把任意 `BCR_LOAD_INVALID` 自动视为首次启动。这样无法区分旧数据和当前格式
  BCR 的掉电损坏，会削弱回滚安全边界。
- 不让烧录脚本通过调试器调用外部 Flash 擦除函数。该方案依赖探针和调试器版本，
  也重现了本次必须人工 SWD 修复的问题。
- 不把首次启动标志只放在外部 Flash。库存板上的任意遗留内容会使该判据不可靠。

## 内部 Flash 一次性请求

### 固定地址

在 Bootloader 的 24 KiB 分区末页保留 `0x08005800-0x08005FFF`，App 仍从
`0x08006000` 开始。链接脚本必须把初始化请求记录固定放在 `0x08005800`，并断言
普通 Bootloader 代码和数据的加载范围不进入该页。

当前 Bootloader 约 12 KiB，保留该 2 KiB 页仍在既有 24 KiB 预算内。发布构建和
RAM/Flash guard 必须继续执行，不能用此估算代替实际构建结果。

### 记录格式

请求记录包含：

- 固定 magic；
- 格式版本 `1`；
- 记录长度；
- 初始化 schema generation `1`；
- 固定选择性擦除 scope bitmap；
- 请求字段 CRC；
- 请求 commit marker；
- completion word，镜像内初值为 `0xFFFFFFFF`。

Combined 构建必须保留该记录。生产重新烧录 Combined 时，编程器擦除并重写所涉及
的内部 Flash 页，completion 恢复为 `0xFFFFFFFF`，从而重新触发一次出厂初始化。
仅写入 `App-N32L406CBL7.bin` 或 OTA App 不接触该页。

初始化完成后，Bootloader 只把 completion word 从 `0xFFFFFFFF` 编程为固定
`INIT_DONE` 值，遵守内部 NOR Flash 的 1->0 约束，不擦除整个标志页。请求头、CRC
或 commit marker 无效时不得猜测或清理外部数据；Bootloader 进入 recovery loop。

## Bootloader 启动顺序

启动顺序调整为：

1. 初始化 Bootloader 所需时钟、GPIO、SPI Flash 和看门狗。
2. 读取并校验内部初始化请求记录。
3. completion 已为 `INIT_DONE` 时不执行任何擦除，继续现有 BCR/镜像选择流程。
4. completion 为 `0xFFFFFFFF` 时执行选择性初始化。
5. 每个外部扇区擦除后完整读取并确认全部为 `0xFF`。
6. 所有扇区均验证成功后，编程并回读验证内部 completion word。
7. 重新执行现有 BCR 加载。擦除后的 BCR 为 `BCR_LOAD_ABSENT`，只有 App 向量有效
   才跳转 `0x08006000`。

任何外部 Flash 识别、擦除、读回或内部 completion 提交失败，都不得跳 App，也
不得把请求标记为 DONE。Bootloader 保持现有有界 recovery step 和看门狗服务；下次
复位会重新执行全部选择性擦除。重复擦除目标扇区是幂等操作。

## 选择性初始化范围

| 用途 | 地址 | 大小 |
|---|---:|---:|
| 配置槽 A | `0x000000` | 4 KiB |
| 配置槽 B | `0x001000` | 4 KiB |
| BCR 槽 A | `0x100000` | 4 KiB |
| BCR 槽 B | `0x101000` | 4 KiB |
| OTA 检查点 A | `0x102000` | 4 KiB |
| OTA 检查点 B | `0x103000` | 4 KiB |
| OTA 授权 A | `0x104000` | 4 KiB |
| OTA 授权 B | `0x105000` | 4 KiB |

初始化代码使用共享布局常量和编译期断言，不复制未经约束的裸地址。擦除清单必须
严格限制在上述八个扇区；测试要证明相邻区域及 Factory、LKG、candidate、盲区和
AGNSS 内容保持不变。

配置槽清空后，现有 App `cfg_init()` 会写入默认配置。终端 PID/设备身份继续由现有
逻辑根据 EC800M IMEI 生成和持久化，不在 Bootloader 中复制身份算法。

## Combined 产物和生产烧录

发布构建必须检查：

- Bootloader ELF 中请求记录位于 `0x08005800`；
- Bootloader BIN/HEX 和 Combined BIN 均包含完整请求记录；
- Combined 的 App 向量仍位于偏移 `0x6000`；
- 请求 completion 在新产物中为 `0xFFFFFFFF`；
- Bootloader 普通代码没有进入保留页；
- 产物未超过 N32L406CBL7 的内部 Flash 边界。

生产烧录脚本必须写入并校验整个 Combined 产物，包含 Bootloader 保留页，然后复位。
脚本不得在烧录后通过 GDB/J-Link Commander 调用外部擦除函数。若编程器未擦除已写
内部页，completion 无法从 DONE 恢复为 `0xFFFFFFFF`，因此脚本必须使用带擦除和
verify 的 Combined 编程模式，并把 verify 失败作为烧录失败。

## 烧录后自检

生产脚本复位后以 `115200 8N1` 监听调试 UART，使用可配置 COM 口和总超时。日志
可能包含 IMEI、ICCID、位置和服务器信息，自检输出及归档必须脱敏。

必检条件：

- 出现 `[BOOT] ready`；
- 出现外部 Flash `JEDEC=684015`；
- 出现 `[4G] ready`；
- 主通道出现 `[808] ch0 ONLINE`；
- 健康日志中 GNSS `RX > 0`、`GGA > 0`、`RMC > 0`、`CS=0`、`FMT=0`。

增强条件：健康日志 `GPS=1` 或日志显示有效经纬度。在室内无卫星环境下，增强条件
未满足只记为 `NO_FIX`，不使生产自检失败。FOTA HTTP 401 记录为警告，不影响本次
核心联网验收。

超时或任一必检条件失败时脚本返回非零退出码，并报告最后到达的阶段；不得自动重刷、
无限重试或修改设备配置。

## 测试与验收

Host 测试至少覆盖：

- 新 Combined 请求触发且只擦除八个目标扇区；
- 全部成功后才写 DONE，随后有效 App 可跳转；
- DONE 状态的普通复位不擦除任何外部扇区；
- 仅 App/OTA 更新不会重新触发初始化；
- 在八次擦除和最终 DONE 编程的每个掉电切点复位，最终都能收敛且保留区不变；
- 擦除失败、读回非 `0xFF`、JEDEC 不匹配、请求记录损坏时不写 DONE且不跳 App；
- BCR 当前格式损坏时仍保持原有 fail-closed，不走首次烧录旁路；
- App 向量无效时，即使初始化成功也不跳转；
- Combined 产物偏移、请求记录和边界检查；
- 自检日志的成功、阶段超时、GNSS NO_FIX、GNSS 校验错误、FOTA 401 警告及敏感字段
  脱敏。

自动验证包括 Bootloader host tests、外部 Flash 布局测试、发布产物测试、Bootloader
构建、App 构建、RAM/Flash/release guards 和 `git diff --check`。

硬件验收需要执行：生产 Combined 烧录、首次启动、重复复位、烧录中/初始化中断电、
EC800M/eSIM 联网、JT808 ONLINE、GNSS NMEA 输入和室外有效定位。上述结果必须分别
标注“已自动验证”和“需要实机/HIL 验证”，不能用 host 测试替代实机结论。
