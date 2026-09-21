# 406 保持功能的优化结果（2026-09-18）

本轮基于用户现有未提交工作树，保留定位、AGNSS、通信、短信、日志管理平台配置及上报、盲区掉电事务和 ACK 消费、OTA 签名/续传/Boot 恢复、继电器安全/超时/恢复。没有迁入 G452 的 RTK/NTRIP，也没有关闭功能或日志。

## 实际修改文件

- `src/debug_uart.c`：十进制/十六进制转换使用统一 do/while 处理零值；提前计算输出长度，去掉逐字符重复计数。临时数组由 32 字节改为 `3 * sizeof(unsigned long)`，覆盖所有调用使用的十进制/十六进制数位。保留宽度、填充、符号、浮点输出及既有小写 `%X` 行为，UART 超时和计数不变。
- `src/jt808.c`：删除没有任何调用的静态 `frame_u32`。保留实际使用的转弯策略包装，不能只因标注 unused 就删除。
- `tools/tests/test_debug_format_equivalence.py`：新增 1024 组全范围确定性整数样本、宽度/补零、浮点整数部分边界及返回长度对照。
- `tools/tests/test_crc32_equivalence.py`：补充真实 CRC 源码与 zlib 的标准向量、页/扇区边界、分块和 checkpoint 初值等价检查。CRC 优化候选无收益，生产实现已恢复为本轮开始时的完整字节内容。
- `docs/superpowers/plans/2026-09-18-preserve-features-size.md` 和本文：计划、结果及验证边界。

没有更改 Makefile、版本、协议、配置结构、Flash 布局、签名信任锚或 Bootloader。G452 只读参考。没有提交、推送、部署、烧录或覆盖原交付固件。

## 同输入实测

使用 ARM GNU 14.3.rel1、当前 Makefile、固定版本头、独立输出目录全量构建。除本轮源码变动外，最终和基线构建配置相同。

| 指标 | 本轮开始 | 最终 |
|---|---:|---:|
| App Flash 加载跨度/BIN | 106372 B | 106356 B |
| 104 KiB 分区余量 | 124 B | 140 B |
| 静态 RAM（map guard） | 17716 B | 17716 B |
| print_uint_width 局部栈帧（GCC .su） | 56 B | 40 B |
| 已知 main 最深调用链帧和 | 2536 B | 2536 B |

净省 Flash **16 B**，格式化函数栈帧减少 **16 B**，不是全程序栈上限减少 16 B。未达到此前建议的 KiB 级余量目标，140 B 仍然紧张。

筛选过的候选：G452 CRC 不内联策略无额外收益；`-Oz` 无额外收益；UART 字符发送禁止内联无收益；27 处纯字面量改为直写使格式化优化后的体积增加 32 B；三个服务模块禁止单次调用内联使体积增加 132 B，静态资源也没有改善。以上均未采用。没有为了缩小体积删掉实际功能。

## 验证证据

工作区 make 可执行文件：`tools/w64devkit/w64devkit/bin/make.exe`。在 A300-first 下执行：

```text
make BUILD=build/optimization-20260918/baseline -o include/build_version.h all
make BUILD=build/optimization-20260918/final -o include/build_version.h all
make BUILD=build/optimization-20260918/final release-gate
python tools/libc_parser_guard.py build/optimization-20260918/final/a300_firmware.map
```

基线和最终构建、Flash 容量限制、release-guard、libc parser guard 通过；Flash guard 仍提示 LOW_HEADROOM。其 CONFIGURATION_CHANGED 是相对门禁自带历史参考，并非本轮前后比较参数不同。

36 项定向测试全部退出 0，命令均为 `python tools/tests/<name>.py`；逐项日志和退出码保存在 `build/optimization-20260918/tests/results.json`：

```text
test_debug_format_equivalence test_debug_uart_stats test_debug_log_levels
test_crc32_equivalence test_feature_guards
test_gps_report_filter test_gps_report_wire
test_agnss_online test_agnss_vendor_stream test_agnss_scheduler
test_agnss_storage test_agnss_snapshot test_agnss_workspace_ownership
test_sms_ingress test_sms_whitelist test_f39_end_to_end
test_at_config_serial_f39 test_log_platform_wire test_cfg_query_f39 test_cfg_query_pass
test_blind_zone_store test_blind_zone_replay test_blind_zone_ack_channel
test_fota_resume test_fota_checkpoint_powercut test_fota_verify_scan
test_firmware_signature test_platform_trust_anchor
test_bootloader_lkg_powercut_c test_bootloader_bcr_failclosed
test_bootloader_invalid_vector_recovery test_bootloader_factory_init
test_remote_relay test_production_relay test_jt808_dual_session test_terminal_identity
```

扩展后的格式化测试也针对本轮开始时的源码快照运行并通过，验证既有输出保持；这是等价重构，不是修复一个原本失败的功能。UART ready/wait/timeout/reset/recovery 覆盖保持通过。

**完整 release-gate 未通过**：release-guard 通过后，在 ram-guard 因全程序栈证据不完整而停止（73 个缺失帧、56 个间接转移、131 个尾转移、1 个环），与前一轮已确认的清理前/后基线缺口一致。未降低门禁。局部 .su 改善和 host 测试不证明全程序 RAM/栈安全。

源码快照、输入哈希、候选构建、最终 map/.su、任务范围 diff 在 `build/optimization-20260918/`。按本轮快照自审而非把用户已有 Git diff 算成本轮改动；git diff --check 检查本轮相关文件。

需要实机/HIL 验证：UART 日志输出与超时、运行栈水位、正常定位/通信/AGNSS，及发布要求中的 OTA/盲区/继电器回归。本轮未进行硬件操作，产物仅用于优化比较，不作为发布验收通过的交付包。
