# V3.084 休眠 0200 时间冻结修复

现场确认：V3.084 进入休眠后仍发送 0x0200，且保持 0x0002 心跳；
`FREQ,30,300#` 设置成功，但周期定位包仍携带休眠前最后一次定位的时间。
提供的报文时间字段为 `26 10 04 19 34 03`（2026-10-04 19:34:03）。

## 根因与最小修改

`work_mode.c` 的休眠调度未删除。8103 的 0x0027 和短信 FREQ 均仍更新
`report_stopped_s`；FREQ 同时启用休眠上报。问题在发送端：
`jt808_send_location_work_mode()` 对休眠周期包调用
`gps_get_last_trusted_location()`，将持续推进的保留时钟替换为定位采集 UTC。
每个周期因而重复使用旧时间，平台显示的定位时间不刷新。

仅在 STATIONARY_SLEEP 的历史位置发送分支改用已有
`gps_get_last_trusted()`：沿用最后可信坐标，使用 SysTick/RTC 推进的事件时间，
仍清除实时定位标志，不声称取得新 GNSS 定位。普通无定位包和 0201 查询继续使用
定位采集时间；NOR 暂存记录重试时仍保持初次序列化的时间。

按本次用户确认，将默认停驻间隔和零值兜底从 180 秒统一为 300 秒。
心跳间隔不变。已有持久化配置不会被覆盖；已设置的 FREQ/8103 间隔仍优先。
GPSDUP,0 仍可显式停止周期定位包，FREQ 可重新启用。
不修改配置结构、Flash 布局、GPIO、休眠唤醒实现或通信协议字段。

## 验证

`python tools/tests/test_sleep_location_reporting.py` 链接真实
work_mode、JT808、GPS、参数处理器及 F39 解析/配置实现，覆盖：

- 300 秒周期、到期前无上报、重复调度无额外包及主/备通道时间。
- 8103 的 0x0027 设置为 60 秒后，休眠上报按新周期执行。
- 用户原指令 `FREQ,30,300#`、GPSDUP 禁用及 FREQ 重启 120 秒周期后的上报。
- 普通无定位包/0201 保留采集 UTC，NOR 重试不改写事件时间。
- SysTick 暂停期间，RTC 累加的休眠秒数仍进入周期包时间。

修复前在 300 秒到期包上失败：分钟字段实际为 00，期望为 05。
修复后测试通过。零值间隔的 work-mode 测试也先在旧 180 秒默认值上失败，
改为 300 秒后通过。原 no-fix 测试仍预期所有旧坐标时间推进，
与 V3.084 的采集 UTC 策略不符；本次明确拆分普通无定位与休眠周期的时间断言。

以下 14 项定向检查实际通过（命令均为 `python tools/tests/<名称>.py`）：
`test_sleep_location_reporting`、`test_jt808_nofix_clock`、
`test_work_mode_policy`、`test_acc_stop1_contract`、
`test_work_mode_jt808_contract`、`test_jt808_params`、
`test_jt808_params_wire`、`test_sms_work_mode_commands`、
`test_at_config_serial_f39`、`test_sleep_wake_timestamp_vibration_contract`、
`test_shallow_sleep_contract`、`test_feature_guards`、
`test_jt808_dual_session`、`test_two_mode_acc_stop1`。

构建及门禁使用 Makefile 和 ARM GNU 14.3.1，输出到独立
`build-sleep-report-20261005/`，未刷新发布版本或覆盖已有发布包：

```powershell
..\tools\w64devkit\w64devkit\bin\mingw32-make.exe BUILD=build-sleep-report-20261005 build-sleep-report-20261005/a300_firmware.hex size flash-guard
..\tools\w64devkit\w64devkit\bin\mingw32-make.exe -s BUILD=build-sleep-report-20261005 release-gate
git diff --check
```

构建、release guard、RAM guard、libc parser guard、平台验签检查及 Flash guard
通过。Flash 使用 105236 / 106496 字节，剩余 1260 字节，门禁有低余量提示。
RAM 门禁计算的 runtime gap 为 4112 / 4096 字节；栈报告仍标记
INCOMPLETE，不能据此声称取得完整全程序栈界限。

检查中发现参数/双平台 host 夹具未补 V3.084 新增的
`gps_get_last_trusted_location()` stub，导致链接失败；补齐测试依赖后通过。
release guard 仍固定要求旧默认值 180，已同步为严格匹配 300，保留其他检查。
额外执行的 `test_release_identity_contract.py` 在版本正则解析处失败：
它硬编码 V3.083，仓库现有发布契约为 V3.084。该既有版本测试问题不属本次
休眠修复范围，未修改；不声称全仓测试全部通过。

本轮修改文件：`src/jt808.c`、`src/work_mode.c`、`src/flash_config.c`、
`include/work_mode.h`、`tools/release_guard.py`、
`tools/tests/jt808_host_support.h`、`tools/tests/test_jt808_dual_session.py`、
`tools/tests/test_jt808_nofix_clock.py`、`tools/tests/test_work_mode_policy.py`、
`tools/tests/test_acc_stop1_contract.py`、新增
`tools/tests/test_sleep_location_reporting.py` 与本文档。

需要实机/HIL 验证：升级后进入休眠，核对相邻 300 秒 0200 的时间推进；
分别用 8103 和 FREQ 设置间隔并抓取出包时间；确认心跳、ACC/震动唤醒和平台展示。
Host 测试与构建不能代替实机、STOP1 RTC 或平台验收。
