# 第二轮保持功能优化（2026-09-18）

基于第一轮完成后的未提交工作树。本轮保留全部功能、日志、协议、持久化格式、OTA 签名与恢复要求，未改 Makefile、版本头、Bootloader 或交付固件。

## 变更

- `src/sha256.c`：SHA-256 消息调度改用 16 字滚动数组，前 16 轮直接读取输入，后续轮在覆盖旧槽前读齐所有依赖；长度编码改为逐字节右移局部副本。上下文结构、摘要、分块接口和原始 bits 计数不变。
- `src/jt808.c`：定位时间的六个 BCD 字段共用转换循环，先写入二位年份/月/日/时/分/秒，再就地编码；时区和报文布局不变。
- `tools/tests/test_sha256_equivalence.py`：实际 C 实现与 hashlib 对照，137 种长度 × 10 种分块，覆盖全部前两块的填充边界、App 最大长度、百万 a 标准向量、上下文交错及 64 位长度编码。支持 `--source` 验证源码快照。
- `tools/tests/test_jt808_dual_session.py`：补充 100 组年份及时间字段的真实 0x0200 解码断言，保留原有时区跨日、闰日和跨年测试。
- `docs/superpowers/plans/2026-09-18-preserve-features-round2.md` 与本文：计划、结果及验证边界。

## 同配置测量

ARM GNU 14.3.rel1，当前 Makefile，固定版本头，独立 BUILD 目录。

| 指标 | 本轮基线 | 最终 | 变化 |
|---|---:|---:|---:|
| App Flash 加载跨度/BIN | 106356 B | 106324 B | -32 B |
| 104 KiB App 分区余量 | 140 B | 172 B | +32 B |
| 静态 RAM（map guard） | 17716 B | 17716 B | 0 |
| sha256_block 局部栈帧（GCC .su） | 336 B | 152 B | -184 B |
| sha256_final 局部栈帧（GCC .su） | 24 B | 16 B | -8 B |
| 已知 main 最深调用链帧和 | 2536 B | 2536 B | 0 |

局部栈帧减少不等于全程序栈上限减少；当前最深已知调用链在 ECC 验签。未测量目标 MCU 执行时间，不声称 CPU 性能提升。Flash 仍为 LOW_HEADROOM，尚未达到 KiB 级余量。

最初保留单独输入循环的滚动数组方案增加 Flash 48 B；合并输入循环后 SHA 方案增加 16 B，BCD 共用循环节省 48 B，合计净省 32 B。SHA 布尔公式替换、摘要输出改为嵌套循环均无额外体积收益，未保留。

## 验证

基线和最终 `make BUILD=build/optimization-round2-20260918/<baseline|final> -o include/build_version.h all` 均通过。工作区 make 路径为 `../tools/w64devkit/w64devkit/bin/make.exe`。

新增 SHA 测试和扩展的双通道报文测试也针对本轮开始时的源码快照通过，验证的是行为等价，不是原有缺陷的 RED→GREEN。回放旧源码时曾遇到相对 gcc 包装器路径错误，改用绝对路径后解决；BCD 测试最初插在未认证阶段，发送断言失败，移至已有在线阶段后基线和最终均通过，未修改生产鉴权逻辑。

27 项最终定向测试全部退出 0，命令为 `python tools/tests/test_<name>.py`：

```text
sha256_equivalence sha256_shared fota_verify_scan fota_resume
fota_checkpoint_powercut fota_package firmware_signature platform_trust_anchor
fota_platform_flow jt808_dual_session gps_report_wire gps_report_filter
jt808_params_wire jt808_first_location jt808_boot_terminal_info
jt808_registration_tx jt808_session_send_failure jt808_send_failure_contract
location_retry_backoff work_mode_jt808_contract stationary_location_owner
blind_zone_store blind_zone_replay blind_zone_ack_channel feature_guards
remote_relay production_relay
```

逐项命令、退出码和日志位于 `build/optimization-round2-20260918/tests/results.json`。签名/OTA 回归包含摘要不符、签名拒绝、包损坏及续传/掉电相关路径。`libc_parser_guard` 通过，任务相关已跟踪文件的 `git diff --check` 通过。

**完整 release-gate 未通过**：release-guard 通过后，ram-guard 因栈证据不完整停止。基线重建及其 ram-guard 同样失败：73 个缺失帧、56 个间接转移、131 个尾转移、1 个环；未放宽门禁。基线门禁曾因 Makefile 跟踪当前源码而重建成候选，随后已用起始源码快照重建并重新验证基线；应以 `baseline-restored-all.log`、`baseline-restored-ram-guard.log` 和 `baseline-verification.json` 为准。

源码快照、输入哈希、最终输入哈希、候选日志、最终 ELF/map/.su 和相对本轮起点的 `task.diff` 位于 `build/optimization-round2-20260918/`。自审确认生产输入仅修改上述两个 C 文件；保留用户其他未提交改动。

需要实机/HIL 验证：OTA 摘要扫描耗时及看门狗服务间隔、运行栈水位、定位报文及发布所需 OTA/盲区/继电器回归。本轮未提交、推送、部署或烧录；实验构建不作为发布门禁通过的交付包。
