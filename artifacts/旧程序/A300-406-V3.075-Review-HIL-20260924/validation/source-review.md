# Flash 余量、代码审查与历史优化整合（2026-09-24）

## 范围与结论

审查对象是 `A300-first` 任务开始时已有未提交修改的工作树，HEAD 为 `27281ba`。
当前可见引用只有本地 `main` 和 `origin/main`；没有其他可直接合并的分支。
历史优化按可见提交、历轮报告、当前源码和测试核对，不声称审查了未提供或不可达分支。
本轮改动已整合到工作树，未创建提交、推送、部署、烧录或覆盖原交付包。

完成了两处业务缺陷修复、有证据的死状态/接口清理以及历史测试契约修复。
同配置独立构建净省 **80 B Flash、32 B 静态 RAM**。这不是大幅容量扩展：
App 仍仅余 **1952 B**，低于 4096 B 告警阈值；全程序栈证据仍未闭合，不能标记正式发布通过。

## 容量实测

工具链 ARM GNU 14.3.Rel1，固定 `include/build_version.h`，使用当前 Makefile、
原有优化参数与分区；基线及最终独立 BUILD，不用旧交付包或 ELF 文件大小推算空间。

| 指标 | 本轮起始工作树 | 最终 verified | 变化 |
| --- | ---: | ---: | ---: |
| App 分区上限 | 106496 B | 106496 B | 0 |
| BIN / map 加载跨度 | 104624 B | 104544 B | −80 B |
| App 剩余 | 1872 B | 1952 B | +80 B |
| 静态 RAM（不含链接器堆栈预留） | 17252 B | 17220 B | −32 B |
| main 已知调用帧和，非最坏上界 | 2624 B | 2624 B | 0 |
| 扣静态 RAM/已知帧后、未扣堆/IRQ/未知路径 | 4700 B | 4732 B | +32 B |

MCU 总 Flash 为 128 KiB，其中 Bootloader 预留 24 KiB；不能将整个 128 KiB 当成 App 容量。
距离 4 KiB 余量仍差 2144 B。Flash guard 内置旧基线报告 `CONFIGURATION_CHANGED`，
其 `delta=-1232` 不用于本轮收益；本轮重新构建的两侧配置 SHA256 相同。

基线 BIN SHA256：`a618e47881b966d8b6f1fc7087cc964b6a0b16a6283ac0e2720714771faf801c`。
最终 BIN SHA256：`b35bf3dbe6e4ca6d23d49ddde42c6e8c1b41981df06fc69425a70b37eca63c94`。

中间候选曾增加 48 B；后续清理后的最终值才是上表结果。删掉已经被 LTO 丢弃的
源码不等于等量释放 Flash，本文没有将删行数或历史各轮节省量累计为本次收益。

## 已修复问题

### 0x8103 改址误重连另一个平台

`src/jt808_params.c` 原来在主/备任一服务器修改时都调用双通道重连，
违反已确认的主备独立规则。现在仅重连发生地址或端口变化的通道，
在旧连接尝试完成通用应答后执行；相同参数不重连，保存失败不产生副作用。
APN/PDP 属于共享网络配置，仍重连双方。身份变更引起的鉴权清理与网络改址分别计算。

JT808 端点位是 0/1，模组通道是 0/3，显式转换掩码，不能直接复用数值。
真实连接管理器原有 OTA 延后与请求合并逻辑保留。
`test_jt808_params` 的修改前失败在 `red/`，最终覆盖主端、备端、双方、重复更新、
APN、配置失败与另一端鉴权保留；连接代次及 OTA 延后由 `test_tcp_endpoint_isolation` 验证。

### 尚未确认的转弯被反向样本抵消后仍进入 ACTIVE

`src/motion_corner.c` 原先仅在超过门槛时写入 TURN_ENTER；随后净角度跌回门槛以下，
旧状态仍可能在确认样本足够时触发转弯。现在每次有效样本重新判定门槛。
新增回归使用可配置的确认数：0°→10°→5°→6°→7°，门槛 10°、确认数 4；
旧实现误触发，修复后无候选。RED 记录在 `red_corner/`。
该缺陷回归不意味着默认 30°、确认数 2 的配置必然遇到同一路径。
默认阈值、已确认候选重试、候选容量、退出采样、最大报告数及超时保留。

### Windows 构建依赖验证失败

Makefile 的配方使用 cmd 语法，但 PATH 中的 sh.exe 可能被 make 选中。
仅在 Windows 设置 `SHELL := cmd.exe`，保留命令行覆盖。
起始 `test_build_dependencies`、`test_flash_gate_build` 失败，修复后通过；
未修改优化级别、编译器、链接地址、容量门槛或版本身份。

## 清理与接口影响

- 删除 `send_frame_broadcast` 已无作用的 `require_all` 参数及三个调用点参数。
  返回值继续以主平台送达为准，副平台仍独立发送；16 个在线/结果组合完整覆盖。
- 删除无生产/测试/启动引用的 `jt808_online_channel` 及声明。
  主平台专属盲区补报、主备独立发送路径保留。
- 删除未再产生的 `JT808_SEND_NO_POSITION`、废弃日志间隔宏及 main 中不可达二次调用。
  未定位报告仍使用历史可信点或零坐标未定位快照；传输/持久化失败仍重试并结束当次调度。
- 删除 EC800M 已失去消费者的 `s_qird_desyncs`、`s_qird_lag` 及无用参数/赋值。
  接收计数、代次匹配、滞后上限、错位断链、恢复和看门狗路径不变；本轮没有新删运行日志。
- 删除转弯 RAM 配置中的 `meaningful_step_deg`、`opposing_noise_deg` 和上下文 `direction`。
  当前算法不读取这些字段，方向由有符号累计角度表达；不更改 Flash 配置记录。
  **内部 C 结构布局变化，相关源模块须一起重编译**，不适用于混用旧预编译对象。
- `tools/release_guard.py` 仅更新已逐项审查的 `jt808.h` 指纹；身份字段和拒绝规则不变。

盘点覆盖 57 个自有 C 模块及配套头文件/启动代码，词法辅助扫描识别 890 个定义。
没有剩余单引用 static 候选；62 个低引用外部候选中包含测试 API、诊断、weak 钩子、
启动及 libc ABI，不能按引用计数删除。扫描会漏掉复杂宏/预处理路径，不是“零死代码”的形式化证明。
SDK、第三方库和产物不作机械清理；未证明可删的兼容接口保留。

## 历史优化核对与整合

| 历史主题 | 当前处理 | 本次验证入口举例 |
| --- | --- | --- |
| V3.057 日志分级、libc exit/堆边界 | 保留现有实现 | debug_log_levels、heap_bounds、libc-parser |
| 第二轮 SHA-256 16 字滚动数组、时间 BCD | 保留 | sha256_equivalence、jt808_dual_session |
| 第三轮 ICCID 直接编码 | 保留 | iccid_encoding_equivalence、terminal_identity |
| 第四至七轮尾转移、间接调用、跳表、机器帧证据 | 保留，未知项不授予安全信用 | stack_tail/indirect/table_targets/machine_frames |
| 第八轮发现的条件 BL/BLX、CBZ 漏报 | 核对第九轮修复已在当前工具中 | stack_conditional_transfers |
| 第九轮 0x8105 复位、先应答后动作 | 保留 | terminal_reset、text_ack_order、remote_relay |
| 第十轮默认配置共用、会话发送记账 | 保留 | flash_config_v3/migration、jt808_session、registration_tx |
| 9月19日高成本体积试验 | 不重新合入曾被拒绝的增大候选 | 当前构建配置未改变 |
| 9月20日坐标/电压/日期/数值等价优化 | 保留原精度和边界 | location_numeric/encoding_equivalence、GPS、mileage |
| 9月20日实际功能修复 | 保留未定位上报、失败60秒重查、旧占位命令ERR | nofix_clock、fota_platform_flow、at_config_serial_f39 |
| 9月21日静止/低速移动过滤 | 保留，未为节省容量关闭 | gps_report_filter、gps_report_wire、stationary_math |
| 9月21日死接口、定位体/F39/DA218E 共用 | 保留 | F39、location encoding、I2C/唤醒相关测试 |
| 9月23日主平台盲区、IP/FIP 隔离 | 保留并补齐 0x8103 同一规则 | blind_zone_ack_channel/replay、tcp_endpoint_isolation |

9月21日记录的“任一通道成功/告警全部成功”已被9月23日用户确认的主平台所有权取代，
不恢复旧规则。移动确认事件的即时补点仍按原设计独立处理，不把它改成新的盲区事务。
这些优化多数已在起始工作树中，本轮是整合验证，不重复 cherry-pick，也不重复计算收益。

## 测试修复原则与过程

起始全量 host 检查有 28 个失败入口，原日志保存在 `baseline/`。
缺失链接依赖的 JT808 测试共用明确的 host 桩；实际 GPS/AT/F39 端到端测试仍链接真实模块。
更新的断言包括：ANGLEREP 关闭保持、未定位上报、主平台盲区责任、FOTA 60秒退避、
已删除可选日志不再作为功能前提、NTP 不冒充可信定位、共用编码函数的真实数据流。
没有让未知命令返回虚假 OK，也没有恢复已过期的业务规则来让旧测试通过。

QIRD 测试继续检查二进制载荷、畸形帧不回调、分包/异步 URC、恢复以及不泄露消息内容。
FOTA 测试继续检查三次尝试、59999/60000ms边界、资源释放、HTTP拒绝、签名/CRC/manifest、
BCR读回及复位顺序。转弯测试旧循环依赖已消费数量生成相同航向导致超时，
改为有界持续航向序列并增加进程超时；该次退出124的原日志保留，遗留测试进程已停止。

最终冻结输入后，**200/200 个 host 测试入口通过，未出现 SKIP**；
另行执行的最终链接必要帧预算通过。包括真实 C/NOR 故障注入、协议回放与源码契约检查，
不能将这些入口都称为实机或完整系统测试。
ARM 构建/Flash guard、release-guard、平台信任锚、libc parser guard、输入哈希复核和
范围内 `git diff --check` 通过。最终构建日志无编译警告。
完整 release-gate 仍失败，见下节；`test_ram_guard` 测试的是门禁工具行为，
其通过不代表本固件的 RAM 验收通过。

首轮最终检查另发现一个依赖广播旧参数形状的 stationary_location_owner 断言，
更新为当前单参数调用后，冻结输入重新运行上述全部200项。各轮失败日志均保留。
最终机器可读汇总在 `build-review-20260924/verification-summary.json`，
记录 `release_approved=false`。

## 未闭合项与验收边界

1. **发布阻断**：release-gate 退出2，首个真实失败为 RAM guard 的 incomplete stack evidence。
   最终缺失帧68、间接转移65、尾转移126、内部调用2、调用环1。
   已知帧预算通过不等于全程序栈、堆及异常嵌套峰值已证明；没有放宽门禁。
2. **容量风险**：1952 B 仍低于4 KiB告警阈值。不能承诺继续新增功能不会溢出。
3. **硬件资料冲突**：工作区指南 ACC=PA3，而当前代码/既有测试 ACC=PA12；
   当前代码的车辆ADC/I2C映射也与部分指南值不同。本轮不改引脚，host契约只验证代码一致。
   需用实际板版本原理图和实机证据定版。
4. **OTA鉴权契约冲突**：指南写设备 API 使用 X-Device-Key，当前固件及专门测试明确不发该头，
   下载采用带令牌URL。此次没有改变鉴权；需要以目标后端部署确认契约，否则可能无法检查/下载。
5. **HIL 未执行**：0x8103主/备改址和APN、OTA期间延后、主断副在线与0x0704 ACK、
   无定位/历史位置切换、转弯/静止抖动及断网/掉电恢复均需要实机/HIL验证。
   未进行 GPIO、低功耗、DMA、模组时序或长期运行的重新验收。

## 证据与复现

证据根目录：`build-review-20260924/`。包含起始1720个输入哈希、src/include/tests快照、
每条命令/退出码/原日志、基线和最终 ELF/BIN/map/stack、最终输入哈希及任务独立差异。
`task-files.json` 列明本轮37个代码/构建/测试文件，区别于用户原有修改；
本报告、执行计划及上述取证脚本/日志另外列为本轮文档和审查产物。
release_guard 起始文件通过单行指纹反向替换重建并匹配起始 SHA256 后纳入 task patch。

```text
python build-review-20260924/audit.py build verified
python build-review-20260924/audit.py tests verified
python build-review-20260924/audit.py gates verified
python build-review-20260924/finish.py verify
```

复跑会追加命令日志；`gates` 目前预期因上述发布阻断退出非零，不应忽略。
真实最终构建在 `build-review-20260924/verified/firmware/`，仅供审查验证，不是已批准发布包。
