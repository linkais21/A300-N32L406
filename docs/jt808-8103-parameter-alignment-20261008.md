# 0x8103 参数 ID 对齐（2026-10-08）

按本轮需求对齐 14 个实际生效 ID 和 10 个兼容设置 ID。

## 实际生效参数

| ID | 用途 | 本轮结果 |
|---|---|---|
| 0x0001 | 心跳间隔 | 保留现有设置、持久化和运行应用 |
| 0x0013 | 主服务器地址 | 保留现有设置和应答后重连 |
| 0x0018 | 主 TCP 端口 | 保留现有设置，不覆盖独立备用端口 |
| 0x0020 | 上报策略 | 保留现有值 0（定时上报），其他策略不支持 |
| 0x0021 | 上报方案 | 保留现有值 0（ACC 方案），其他方案不支持 |
| 0x0027 | 休眠/停止上报间隔 | 保留现有设置和运行应用 |
| 0x0029 | 默认/移动上报间隔 | 保留现有设置和运行应用 |
| 0x0055 | 最高速度 | 保留现有 20..200 km/h 范围 |
| 0x0056 | 超速持续时间 | 新增 DWORD 秒数设置、持久化、查询和实际超速判定 |
| 0x0080 | 总里程 | 保留现有 0.1 km 到米的转换 |
| 0x0081 | 省域 ID | 保留 WORD 设置 |
| 0x0082 | 市县域 ID | 保留 WORD 设置 |
| 0x0083 | 车牌 | 保留 GBK 字节和身份更新 |
| 0x0084 | 车牌颜色 | 保留 BYTE 设置和身份更新 |

0x0056 接受 0..4294967 秒（UINT32_MAX / 1000），避免毫秒计时转换溢出。
显式 0 表示在首次符合原有超速条件的采样上触发；未设置或旧配置使用原有 10 秒默认值。
仍保留有效实时定位、合法限速、持续超速、每段只触发一次和 300 秒告警冷却约束。

持续时间和有效标记使用原 `_reserved[24]` 最后 5 个字节：前 19 字节保留。
配置大小仍为 788 字节，PID 偏移仍为 684，device_api_key 偏移仍为 756，CFG_VERSION 仍为 4。
复用原 A/B 配置 CRC、generation、commit marker 和写入失败回滚机制，不另建存储事务。

## 兼容设置参数

0x0002、0x0003、0x0004、0x0022、0x0028、0x002C、0x002E、0x002F、0x0030、0x0031：
每项必须为 4 字节 DWORD；有效的 0x8103 事务返回通用应答成功（result=0）。
这些项只用于兼容平台必选下发，值不保存、不改变运行参数，也不加入 0x0104 查询结果。
仅设置兼容项时不擦写 Flash、不重新配置外设、不重连服务器。

兼容项仍参与长度、重复 ID 和整包校验；混合下发中的任意非法项、未知 ID、重复 ID、截断或多余字节会拒绝整包，不部分应用。
未知 ID 仍返回不支持（result=3），错误长度仍返回消息有误（result=2），存储/工作区失败仍返回失败（result=1）。
去重位图覆盖全部 29 个受理 ID，添加编译期不超过 32 项约束。
0x8104 全量查询增加实际生效的 0x0056，返回 19 项原有及新增可查询参数。

## 实际验证

- 兼容组：修改前真实 C handler 测试断言失败；补齐后通过。
- 0x0056：隔离编译 HEAD 中原 handler 与当前 handler，同一 3 秒设置报文分别得到拒绝（RED）和成功（GREEN）。
- `python tools/tests/test_jt808_params.py`：PASS。含全部 24 项同包下发、重复下发、混合事务回滚、长度/值边界、查询与保存，以及设置到超速判定的 3 秒边界。
- `python tools/tests/test_jt808_params_wire.py`：PASS。真实 RX、主备通道 ACK、查询编码和全量查询。
- `python tools/tests/test_overspeed_policy.py`：PASS。原 10 秒行为、0/3/30 秒、计时回绕、无效定位恢复、冷却、上限和溢出拒绝。
- `python tools/tests/test_flash_config_v3.py`：PASS。真实 NOR 模型、配置偏移、重启保持和原有事务掉电切点包含新增时间字段。
- `python tools/tests/test_flash_config_migration.py`：PASS。历史配置迁移回归。
- `python tools/tests/test_jt808_dual_session.py`：PASS。
- `python tools/tests/test_f39_config.py`：PASS。
- `mingw32-make.exe BUILD=build-params-20261008 build-params-20261008/a300_firmware.hex size flash-guard -j4`：PASS。在独立构建目录使用原 Makefile，保留当前 build_version.h。Flash 使用 105532/106496 字节，剩余 964 字节；链接 RAM 区使用 19132/24576 字节。
- `mingw32-make.exe BUILD=build-params-20261008 ram-guard`：FAIL。第一个门禁失败为 `stack evidence: IRQ policy source changed: src/main.c`；栈报告仍是 INCOMPLETE，未证明全程序栈/堆/异常上界。未修改策略或削弱门禁，本次不能标为发布验收通过。

需要实机/HIL 验证：平台混合下发、配置重启保持、有效超速采样的实际告警时机、主服务器/身份更改后的注册重连，以及原有心跳和上报间隔应用。
本轮未烧录、提交、推送或部署。

## 本轮触碰文件

- `include/jt808_params.h`、`src/jt808_params.c`
- `include/flash_config.h`
- `include/overspeed_policy.h`、`src/overspeed_policy.c`
- `src/main.c`：仅增加超速持续时间入参，保留已有用户修改。
- `tools/tests/test_jt808_params.py`、`tools/tests/test_jt808_params_wire.py`
- `tools/tests/test_overspeed_policy.py`、`tools/tests/test_flash_config_v3.py`
- 本文档；独立构建输出位于 `build-params-20261008/`。
