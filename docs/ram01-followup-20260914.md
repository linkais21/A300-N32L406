# RAM-01 后续修复与 FOTA/GNSS 核实

2026-09-14。用户已确认 uptime 112 分钟附近的反复 ACC 切换为人工测试，本轮不修改 ACC 状态机或引脚。原日志不能确认全程静止，因此里程准确性仍保留条件。

## RAM：减少父函数栈帧叠加，完整安全验收仍未关闭

原 V3.043 日志全部 150 条 HEALTH 为 F=1，RAM_GAP=4088 B，低于 4096 B。重新构建当前源码复现最终 LTO 的 main=792 B、fota_process=1208 B；实际反汇编 main 入口一次分配大帧，命令处理局部数组因内联进入长期存活的 main 帧。

最小修复是为 `at_config_process` 和 `send_request` 保留 noinline 函数边界。前者隔离命令/回复局部数组，后者隔离 HTTP 请求缓冲，避免它们抬高无关分支调用的栈基数。不改全局优化参数、不将数组改为静态常驻、不减少缓存、不降低 4096 B 门限。HTTP 字节内容、OTA 状态机、持久化布局及错误处理不变。

新测试 `tools/tests/test_ram01_frame_budget.py <build目录>` 校验 ELF/MAP/.su/manifest 哈希绑定后检查必要预算。基线因 3696 < 4096 出现预期断言失败；最终产物通过。该测试不能代替 release gate。

| 实际最终链接数据 | 本轮同源基线 | 仅函数边界实验 | 最终含 GNSS 诊断 |
|---|---:|---:|---:|
| main 单帧 | 792 B | 392 B | 392 B |
| fota_process 单帧 | 1208 B | 968 B | 968 B |
| 已知主循环最长帧链 | 2984 B | 2528 B | 2528 B |
| 静态 RAM（MAP .data+.bss） | 17896 B | 17880 B | 17896 B |
| SRAM - 静态 RAM - 已知帧链 | 3696 B | 4168 B | 4152 B |
| App Flash | 105160 B | 105104 B | 105208 B |
| App Flash 余量 | 1336 B | 1392 B | 1288 B |

最终相对基线：已知帧链减少 456 B，静态 RAM 不变，Flash 增加 48 B。函数边界实验节省 16 B 静态 RAM，被诊断对象及对齐开销抵消；不能只从三个 uint32_t 推断最终 MAP 增量。

最终最长已解析帧链变为 main → fota_process → send_request → ec800m_tcp_send → at_send_wait_owned → process_rx_byte → process_rx_line → sms_ingress_feed_line → root_ok → eq。单独 send_request=712 B，at_config_process=720 B，主帧缩小不是这些局部数组消失。

**完整 RAM/release gate 仍失败，未批准发布。** 最终报告保留 91 个缺少帧的符号、56 个间接转移、117 个跨符号尾转移及 1 条调用环诊断；还缺完整库函数、回调/尾调用、有限重入、堆峰值及 Cortex-M4 IRQ/FPU 异常帧证据。4152 B 仅比最低门限多 56 B，尚未扣这些未知量。当前工具为 incomplete 是正确行为，本轮不修改 gate 的拒绝策略。

这里的静态帧链不是实测 STK_PEAK，也不能推断新固件 F 已清零。原实机日志只能证明旧镜像的症状；新的 runtime gap/栈峰值需要实机/HIL 验证。

## FOTA 401：已复现入口拒绝，不能以加 Key 代替契约核实

当前固件请求没有 X-Device-Key；`test_fota_no_api_key_contract.py` 明确要求无共享 Key，实际 OTA host 流程验证检查无需共享 Key、下载使用任务 token。当前本地后端 DeviceUpdateController 与 SecurityConfig 也采用该流程。但用户工作区指南要求 X-Device-Key，这是明确冲突，本轮没有选择其中一个改实现。

执行未携带设备身份及凭据、也未携带有效检查参数的只读请求：

```text
curl.exe --noproxy '*' -sS -i --max-time 15 http://<日志FOTA主机>:8088/api/device/updates/check
HTTP/1.1 401 UNAUTHORIZED
Server: gunicorn
Content-Type: text/html; charset=utf-8
Content-Length: 317
```

默认代理请求也返回相同类型的响应；最初沙箱直连被拒绝，按权限流程获准后重试直连，得到上述结果。探测没有传入实际 deviceId，不会通过本地控制器的签到路径创建测试设备。

线上入口响应为 gunicorn HTML，与本地 Spring Boot JSON 接口实现不一致。可确认鉴权拒绝仍存在，优先排查实际部署服务、8088 端口目标及反向代理；单凭 Server 头不能证明请求抵达哪个后端，也不能断言是错误端口、旧版本或特定中间件。未获取生产服务配置、容器镜像版本或访问日志，因此根因未最终关闭。后续应只读对照部署路由和访问日志，确认正式鉴权契约后再改相应一侧；不删鉴权、不默认加入 Key、不暴露凭据。本轮未登录服务器、部署或重启服务。

原日志 401 后未再检查，与当前 6 小时周期相容；实机窗口约 2.5 小时。新增 noinline 没有改变该行为。

## GNSS：回放复现丢弃路径，新增可区分的现场证据

旧日志 DROP=108→184 只能确认软件丢句，无法区分队列满与超长；OREF 更没有计数。实际 `gps.c` host 回放证明：不运行 gps_process 连续喂入三句，两槽队列接收两句、第三句被丢弃；超长输入另一路触发丢弃，之后有效句可恢复解析。这些是可复现机制，不代表旧日志的 184 次已全部归因。

新增每分钟 GPS 日志字段：

| 字段 | 含义 |
|---|---|
| DROP | 保留原累计软件丢句 |
| QDROP | 句子起始时队列满，最终换行计入的丢句 |
| LDROP | 捕获过程中超出容量，最终换行计入的丢句 |
| OREF | ISR 观察到硬件 overrun 的次数，不等于丢失字节/句子数 |

保留两槽、128 B 容量、每次主循环处理一条的行为；ISR 只增加常数时间计数。gps_diag_t 是内部诊断接口，本轮追加三个 uint32_t，无 Flash 持久化或通信协议变更。计数仍为 uint32_t 累计值，会自然回绕；单次日志读取不是所有 ISR 计数的原子快照。

独立审查发现必须先采样 OREF 再读数据：SDK 说明状态寄存器读取后读取 DAT 会清除 OREF。补充 RXDNE/OREF 同时置位测试，修改前计数断言失败；修复后先采样 OREF，RXDNE 分支只读并交付一次，OREF-only 分支只做清除读取。没有引入双重读取数据。复审通过。

下一轮采集重点是 QDROP/LDROP/OREF 的增长与启动、AT/NTP 等有界但阻塞调用的相关性。现有 AT 等待期间未服务 gps_process，队列压力是可疑路径，但本轮没有增加跨模块重入调用或声称解决现场丢句。若 QDROP 增长，再测最大服务间隔并缩短阻塞；若 LDROP 增长，核对实际 NMEA 句长/格式；若 OREF 增长，检查 IRQ 服务延迟。均需要实机/HIL 验证。

## 本轮验证

所有 make 使用 `D:/A300_Tools/toolchains/make-4.4.1/bin/make.exe`，在 A300-first 下执行；产物隔离在 `build/ram01-followup-20260914/`。最终编译仍保留 LTO 与 -Os，未打包为新版本发布。

- `make -B all [stack-report] BUILD=build/ram01-followup-20260914/<baseline|candidate|final>`：各阶段成功；OREF 复审修复后又运行 `make all stack-report BUILD=.../final`，编译链接成功，Flash gate 提示 LOW_HEADROOM/CONFIGURATION_CHANGED。
- `python tools/tests/test_ram01_frame_budget.py .../baseline`：预期 RED，3696 < 4096；`.../final`：PASS，4152 B。完整分析仍 incomplete。
- `python tools/tests/test_gps_drop_diagnostics.py`：缺失接口最初编译失败；声明接口后正确出现队列分类断言 RED，实现后 GREEN；增加同时 RXDNE/OREF 后再次 RED，调整状态采样顺序后 GREEN。覆盖两槽队列满、超长、正常解析恢复、初始化清零、OREF-only、同时置位、不重复读取与交付。
- GNSS 既有脚本 `test_nmea_replay.py`、`test_gps_ntp_apply.py`、`test_gps_tx_bounded.py`：修复后通过。
- `python tools/tests/test_fota_platform_flow.py`：五组流程通过，包含真实生产解析/manifest/哈希/CRC/验签门控、失败拒绝、掉线恢复和调度。
- 11 项定向脚本通过：`test_at_config_serial_f39`、`test_f39_end_to_end`、`test_fota_checkpoint_powercut`、`test_fota_modem_handoff`、`test_ram_watermark`、`test_stack_health_observability`、`test_heap_bounds`、`test_lto_stack_guard`、`test_feature_guards`、`test_fota_no_api_key_contract`、`test_production_selftest`（均为 tools/tests 下 .py 文件）。日志及退出码保存在 tests.json 和同名 .log。
- `python tools/libc_parser_guard.py .../final/a300_firmware.map` 与 `python tools/tests/test_platform_trust_anchor.py`：通过；后者执行真实平台签名及篡改拒绝。
- 最终 `make release-gate BUILD=.../final`：退出 2。release-guard 通过；RAM gate 在 incomplete stack evidence 处拒绝，未执行其后所有依赖，不能声称完整发布门禁通过。
- 早期测试按精确函数声明查找 send_request，直接插入属性使其查找失败；最终采用独立 noinline 声明保留接口，相关测试已重跑通过。没有删除契约断言。
- 最终默认配置 `git diff --check` 退出 0；新增报告/计划/测试的 UTF-8、行尾空白以及最终产物哈希核对通过。

最终 BIN SHA-256：`4f8553a7d0445e552da9363a9a89daa26f734c8fb873ef50dd8e3946167c6a81`。资源对比及基线/候选哈希见 comparison.json；最终 .su、MAP、反汇编和 stack-analysis.json 可追溯。源码仍显示 V3.043，仅作为未发布工程诊断构建；不得将本轮构建覆盖 V3.043 已归档发布物。

本轮实际改动：src/at_config.c、src/fota.c（仅 noinline 声明）、src/gps.c、src/main.c、include/gps.h；新增两项定向测试、执行计划和本报告；在 serial-review-20260914-v3043.md 追加用户的 ACC 确认。其他既有工作树修改保留。未提交、推送、烧录、发送设备控制或部署。
