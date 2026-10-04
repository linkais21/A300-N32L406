# APN 配置重复重连修复（2026-09-20）

范围：配置查询执行确认及 F39 APN 重连判定。保留已有用户改动；未修改设备平台、网络驱动、定位、报警或继电器实现，未提交、发布或烧录。

## 行为

- 配置查询复用 `at_config_execute_text_command_ack`：校验、持久化成功后，在网络副作用之前发送原有 `0x14` 确认。帧格式、设备身份校验、查询周期和超时保持原契约。
- 持久化/命令失败不发送成功确认；确认发送失败仍返回 `result=-1`。已经保存的网络配置仍应用，平台后续重发可再次确认。
- APN 模式、名称、用户名、密码均相同时，不再重启 PDP。实际配置或凭据改变仍重启；DUALSET 的其他副作用保持执行。
- 确认沿用原有 UDP 发送结果，不等于服务端已收到。如果确认丢失，相同 APN 再次下发可重试确认而不重复重启网络。

## 本轮修改文件

- `src/cfg_query.c`
- `src/f39_config_adapter.c`
- `tools/tests/test_cfg_query_f39.py`
- `tools/tests/test_cfg_query_pass.py`
- `tools/tests/test_cfg_query_lifetime.py`
- `tools/tests/test_f39_config.py`
- 本文档

## 自动验证

`python tools/tests/test_cfg_query_f39.py` 使用真实 cfg_query → at_config → F39 → 配置事务实现，模拟 PDP 重启后退出 READY。

RED：修复前发送确认时触发 `modem_ready` 断言；仅调整确认顺序后，重复 APN 仍触发 `pdp_restarts==2&&modem_ready` 断言。两项修复后 GREEN。

覆盖：自动/手动 APN、重复下发、确认失败后重发、用户名/密码单独变化、持久化失败、无效命令、DUALSET 中相同/不同 APN 与频率修改，以及原有 HBT/FREQ/IP 和继电器拒绝路径。

以下脚本通过（均以 `python tools/tests/<名称>.py` 运行）：

```text
test_cfg_query_pass
test_cfg_query_lifetime
test_cfg_query_f39
test_cfg_query_contract
test_text_ack_order
test_f39_config
test_f39_dualset
test_f39_parser
test_f39_actions
test_f39_end_to_end
test_at_config_serial_f39
test_at_config_handoff
test_ec800m_udp_transaction
test_ec800m_udp_wire
test_ec800m_udp_async_contract
```

`test_f39_config` 原断言要求已经处于 AUTO 时再次重启；按新的幂等行为更新这两项期望后通过，其他断言保留。

通过本机 STM32CubeIDE 安装的 make 执行：

```text
make all BUILD=build-apn-ack-fix-20260920
make release-guard ram-guard stack-guard BUILD=build-apn-ack-fix-20260920
```

- ARM GNU 14.3.1 编译、链接和 Flash guard 通过。App 使用 105084 / 106496 字节，剩余 1412 字节；保留 LOW_HEADROOM 和 CONFIGURATION_CHANGED 提示，不能用其历史差值声称本轮节省空间。
- release-guard 通过。
- ram-guard 失败：栈证据 incomplete（68 个缺失帧、66 个间接跳转、133 个尾跳转、2 个内部调用、1 个循环），未证明整程序栈/堆/异常上界。已知调用帧和为 2536 字节；诊断余量 4760 字节不是完整栈安全证明。随后 stack-guard 未执行。
- 原 `build/stack-analysis.json` 也标记 incomplete，但并非与本轮输入一致的基线，不能据此声称本轮栈变化已经完全验证。
- `git diff --check` 范围内检查通过。

验证产物与日志位于 `build-apn-ack-fix-20260920/`、同名前缀的构建/门禁日志。该目录为测试构建，不是发布包；没有分配新发布版本。输入摘要记录在该目录的 `source-sha256.json`。

## 需要实机/HIL 验证

1. 对已处于自动 APN 的设备重发 `APN,AUTO#`：平台应转为配置成功，至少观察 5 个查询周期，无每分钟重连。
2. 使用已确认可用的 APN 做一次真实变更：确认与网络恢复正常；重复相同参数不再重连。
3. 注入确认丢失，恢复通信后重发：平台能完成任务，不进入重复网络重建循环。
4. 检查配置执行期间及重连后的定位、心跳、双通道上线和栈水位。通过前不能宣称实机问题已消除或固件满足发布门禁。
