# 0x8103 审核与 0x005B 超速预警（2026-10-15）

## 审核结论

审核对象为当前 N32L406 固件参与构建的源码，未使用历史固件作为实现依据。
本轮保留已有的 14 个生效 ID 和 10 个兼容设置 ID，增加实际生效的 0x005B。
审核和修改没有提交、推送、部署、烧录或发送真实设备控制命令。

| 生效 ID | 当前支持范围 / 应用路径 |
|---|---|
| 0x0001 | DWORD 秒，1..3600；保存后更新心跳及工作模式调度 |
| 0x0013 | STRING 主服务器；事务保存、旧连接应答后重连主通道 |
| 0x0018 | DWORD 主 TCP 端口，1..65535；不覆盖独立 FIP 端口 |
| 0x0020 | DWORD，仅支持 0（定时上报）；其他策略返回 result=3 |
| 0x0021 | DWORD，仅支持 0（ACC 方案）；其他方案返回 result=3 |
| 0x0027 | DWORD 停止上报秒数，5..18000；更新工作模式调度 |
| 0x0029 | DWORD 移动上报秒数，5..18000；更新工作模式调度 |
| 0x0055 | DWORD 限速，20..200 km/h；超速报警和新增预警均读取此值 |
| 0x0056 | DWORD 超速持续秒数，0..4294967；控制正式超速报警 bit1 |
| 0x0080 | DWORD，0.1 km 转换为内部米数；拒绝乘 100 溢出 |
| 0x0081 / 0x0082 | WORD 省域/市县 ID；保存后使注册身份更新 |
| 0x0083 | STRING GBK 车牌；校验完整字符、保存后更新注册身份 |
| 0x0084 | BYTE 车牌颜色，0..4 或 9；保存后更新注册身份 |
| **0x005B（新增）** | **WORD 超速报警预警差值，单位 0.1 km/h；保存、查询、实际预警** |

0x0002、0x0003、0x0004、0x0022、0x0028、0x002C、0x002E、0x002F、0x0030、0x0031
仍为兼容设置项：严格要求 DWORD（4 字节），正确事务返回成功，但不保存、不参与查询、不改变运行行为。
只有兼容项的事务不擦写配置、不重连；混合事务的非法项使整包拒绝，不部分应用。

## 协议与行为

依据工作区 `protocol/道路运输车辆卫星定位系统北斗兼容车载终端通讯协议技术规范协议(808部标2013).docx`
参数表和位置报警标志表：0x005B 类型为 WORD，单位为 1/10 km/h；超速预警为报警标志 bit13，维持至条件解除。
本轮只读取并解析原 DOCX 的 XML，没有改写协议原件。

- 设置包每项采用 `00 00 00 5B 02 HH LL`，大端 WORD，接受 0..65535。
- 例如单项消息体 `01 00 00 00 5B 02 00 64` 设置差值 100，即 10 km/h。
- 门槛为 `max(0, 限速×10 - 差值)`，比较当前速度×10。限速 100 km/h、差值 100 时，89.9 不预警，90.0 开始预警。
- 显式设置 0 表示无提前量，在到达限速时预警。差值大于等于限速×10 时门槛饱和为 0，静止不触发；仍要求正速度。
- 必须处于实时工作模式，并有新鲜、有效定位；拒绝 NaN、无穷及无法表示为协议速度的值。休眠、无效/过期定位和保留位置不生成新预警。
- 首次进入预警条件时，经现有 `work_mode_notify_alarm()` 路径排队立即上报；条件持续时不重复产生边沿事件。
- 共享位置编码器按本次快照重新计算 bit13，因此发送成功不会清掉持续预警，条件解除后的新报文会清零；不从已排队的 bit13 事件恢复过期状态。
- 失败发送仍使用现有盲区事务，保存事件当时已经编码的报警标志；历史盲区记录不按当前参数重算。
- 正式超速报警 bit1 保留原来的严格超速、持续时间、每段只触发一次及 300 秒冷却。0x005B 不修改该状态机。

旧配置没有显式设置时默认关闭新增预警；0x0104 对旧配置的 0x005B 返回 WORD 0。
新配置显式设置 0 后有效标记置 1，与旧配置默认关闭状态区分。
全量 0x8104 查询由 19 项变为 20 项；0x8106 支持单独查询 0x005B。
参数表由 29 项变为 30 项，仍受不超过 32 项的编译期去重位图约束。

## 持久化和代码审查

从 `_reserved[19]` 尾部取出两个大端值字节和一个有效标记，剩余 `_reserved[16]`。
`device_config_t` 仍为 788 字节，PID 偏移 684，device_api_key 偏移 756，CFG_VERSION 仍为 4；
0x0056 字段、既有配置前缀及后续字段偏移不变。复用现有 A/B、CRC、generation、最后提交 marker、失败回滚和 owner 锁。

修改文件：

- `include/flash_config.h`、`include/jt808_params.h`、`src/jt808_params.c`：配置字段、参数设置和查询。
- `include/overspeed_policy.h`、`src/main.c`：有界预警条件及前台上升沿通知。
- `include/jt808.h`、`src/jt808.c`：标准 bit13 与共享位置编码。
- `tools/release_guard.py`：在已有用户修改上，仅更新新增 bit13 常量所在头文件的审核指纹。
- `tools/exception_stack_guard.py`：仅更新已复核的 main.c 指纹。相对本轮起点的差异只在前台 `scan_alarms()`；中断处理、NVIC/FPU 策略、HardFault、boot_init 和主循环次序未改。保留所有拒绝路径及资源阈值。
- `tools/tests/test_jt808_params.py`、`test_jt808_params_wire.py`、`test_overspeed_policy.py`、`test_flash_config_v3.py`：新增回归。
- 本文档：参数审核、行为约定、验证与 HIL 项。

工作树已有的里程、V3.092 发布身份和相关测试修改均予以保留。
普通 `make all` 会自动刷新发布身份时间戳；本次发现后依据现有 V3.092 交付清单的三个源码 SHA256 恢复了
`include/build_version.h`、`include/config.h`、`release_identity.json`，再以 `-o include/build_version.h` 验证构建。
没有覆盖已有固件交付包；构建产物只放在忽略的独立诊断目录。

## 自动验证

RED→GREEN：新增参数测试在原 handler 上因 0x005B 返回不支持而断言失败；实现后通过。
`python tools/tests/test_jt808_params_wire.py --baseline-warning` 在临时目录编译 HEAD 的扫描/位置编码源码，
保留当前参数 handler，按预期在首次预警通知断言处失败。正常运行同一测试通过，未重置工作树。

以下实际执行通过：

```text
python tools/tests/test_jt808_params.py
python tools/tests/test_jt808_params_wire.py
python tools/tests/test_overspeed_policy.py
python tools/tests/test_flash_config_v3.py
python tools/tests/test_flash_config_migration.py
python tools/tests/test_jt808_dual_session.py
python tools/tests/test_work_mode_jt808_contract.py
python tools/tests/test_gps_report_wire.py
python tools/tests/test_jt808_nofix_clock.py
python tools/tests/test_jt808_send_failure_contract.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_release_identity_contract.py
python tools/tests/test_feature_guards.py
python tools/tests/test_flash_capacity_guard.py
python tools/tests/test_ram_guard.py
python tools/tests/test_ram_release_budget.py build-005b-review-20261015
python tools/release_guard.py
```

覆盖：WORD 边界 0/65535、错误宽度、截断、尾随字节、重复/未知 ID、工作区争用、保存失败、混合 25 项事务、重复设置、查询及重载；
真实 NOR 单向写/擦除和配置写入各失败切点；预警门槛、持续/解除、重入、主/备通道、历史/过期/休眠定位、盲区记录，及正式超速报警三秒边界。

构建和资源门禁使用工作区的 `tools/w64devkit/w64devkit/bin/mingw32-make.exe`，在固件仓库执行等价命令：

```text
mingw32-make.exe -s -o include/build_version.h BUILD=build-005b-review-20261015 TOOLCHAIN_DIR=<repo>/.toolchain/bin all ram-guard
```

环境变量中的外部工具链路径首次调用返回 Access is denied；改用仓库现有 `.toolchain` 入口后构建成功。
门禁首次因新增头文件常量及 main.c 的审核指纹失配拒绝，完成上述差异审查后更新指纹并重新验证通过。

- App Flash：105936 / 106496 字节，余 560 字节，容量门禁 PASS，保留 LOW_HEADROOM 提示。
- 静态 SRAM：16056 字节；对齐 4 字节；硬堆保留 1024 字节。
- 审核覆盖的启动/主调用栈 2804 字节，嵌套异常预算 584 字节，剩余 4104 / 要求 4096 字节，完整 RAM 预算门禁 PASS。
- 独立栈图仍报告不可达/未纳入执行根证明的缺口，因此单独 `stack-report` 状态为 INCOMPLETE；完整 RAM 门禁依赖原有审核执行根和异常证明，没有消除或忽略报告缺口。
- IRQ 指纹、工具链/FPU 配置、未知可达调用和中断向量篡改的拒绝测试均通过。

当前诊断构建身份与已有 V3.092 相同，仅用于代码验证，不作为新的发布交付包。

## 需要实机/HIL 验证

未执行实机验证。需要在隔离设备/平台环境完成：

1. 下发示例包，应答成功，0x8106/0x8104 返回 `00 64`，断电重启仍保留。
2. 设置限速 100、持续 3 秒、差值 100，回放 89.9→90→101→89.9 km/h；核对 bit13 保持/解除、bit1 三秒触发以及平台显示。
3. 核对实时模式、定位失效/恢复、休眠唤醒及主/备链路断开后的盲区补传；历史记录保持事件时值。
4. 运行 RAM 水位和实际业务压力验证；Flash 余量 560 字节、资源预算仅比 4096 字节门槛多 8 字节，后续改动必须重新运行门禁。
