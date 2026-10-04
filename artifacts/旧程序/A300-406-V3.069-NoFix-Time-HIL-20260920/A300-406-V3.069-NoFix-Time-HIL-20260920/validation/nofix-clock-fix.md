# 无定位时 0200 时间持续推进

## 现象与根因

输入日志：工作区 `ReceivedTofile-COM13-2026_9_20_13-47-52.DAT`。
第 545、592、623 行等出现 `0200 fallback=last-trusted`，伴随 GPS 无效和工作模式切换。
日志未提供可直接解码的完整 0200 帧，因此包内时间冻结由用户现场观察、源码路径和 host 复现共同确认。

`jt808_send_location_work_mode()` 在实时定位不可用时读取保留快照。
旧逻辑仅在浅休眠或 STOP1 时推进快照时间；浅休眠结束、GPS 开启后停止推进，
导致仍未重新定位时新生成的 0200 重复上次时间。

## 修复范围

- `src/gps.c`：以 SysTick 推进保留 UTC，保留不足一秒的余量；处理 tick 回绕，
  在 GPS 处理和快照读取时更新；新快照和 NTP 校时重新设置计时基准。
- `src/main.c`：移除浅休眠专属补时，避免与 GPS 内统一计时重复；STOP1 RTC 补时保留。
- `include/gps.h`：说明自动推进时间及 STOP1 补时接口的适用范围。
- 新增 `tools/tests/test_gps_retained_clock.py`、`tools/tests/test_jt808_nofix_clock.py`。
- 更新 `tools/tests/test_shallow_sleep_contract.py`；修正
  `tools/tests/test_acc_bounce_hardening.py` 对旧包装函数的检查，改为检查实际快照实现及委托关系。
  后者的旧断言在本轮修改前源码上也失败，实际防回退逻辑仍然存在。

历史坐标、未定位状态、配置时区及盲区记录格式不变。新事件使用推进后的时间；
已生成的盲区事件在重试/补传时保留事件原时间。尚未取得过可信快照时不伪造定位。
本次未改变可信快照的采集策略，也未新增冷启动无定位上报能力。

## 已自动验证

`python tools/tests/test_gps_retained_clock.py` 修复前因 30 秒后时间未推进而失败，修复后通过。
覆盖持续无定位、200 ms 频繁读取、GPS 开关、STOP1 RTC 补时、跨年、闰日、tick 回绕、
重新定位/旧时间拒绝、NTP 校时及重新初始化。

以下命令均通过（各项执行 `python tools/tests/<文件名>`）：

- `test_gps_retained_clock.py`
- `test_jt808_nofix_clock.py`：链接实际 gps.c 和 jt808.c，解码主备链路 0200，
  验证 UTC+8 时间按 10 秒递增、未定位状态不变、盲区重试时间不被改写。
- `test_gps_ntp_apply.py`
- `test_shallow_sleep_contract.py`
- `test_acc_bounce_hardening.py`
- `test_acc_stop1_contract.py`
- `test_work_mode_jt808_contract.py`
- `test_gps_report_wire.py`
- `test_jt808_dual_session.py`
- `test_blind_zone_replay.py`（含 mutation）
- `test_feature_guards.py`

通过仓库现有 Make 包装入口执行 `all BUILD=build-nofix-clock-20260920`，
ARM GNU 14.3 构建通过；Flash 使用 105152 / 106496 字节，剩余 1344 字节，
Flash guard 通过并提示 LOW_HEADROOM / CONFIGURATION_CHANGED。
`release-guard` 通过。范围内 `git diff --check` 无空白错误。

构建自动刷新了 `include/build_version.h`、`include/config.h`、`release_identity.json`
的时间戳至 `20260920145822`，版本号仍为 V3.068；不是新版本发布。
验证构建放在独立目录，未覆盖既有交付目录，未烧录、部署或提交。

## 未通过 / 未验证

`ram-guard BUILD=build-nofix-clock-20260920` **未通过**：全程序栈证据不完整
（missing frames=68、indirect transfers=66、tail transfers=133、internal calls=2、cycles=1）。
静态 RAM 诊断为 17280 字节，已知调用栈为 2536 字节；不能据此证明完整 RAM 预算合格。
详见 `../build-nofix-clock-20260920/guards.log`。
现有 `make.CMD` 包装器返回 0，但内部明确报告 `ram-guard Error 1`，本记录按实际失败处理。
本次未修复无关构建包装器或扩大到全程序栈审计。

**需要实机/HIL 验证**：取得可信定位后屏蔽 GNSS，持续观察 0200 时间与当前时间同步推进，
再覆盖 ACC 反复切换、长时间无定位、浅休眠及启用 STOP1 的 RTC 唤醒。
平台应显示未定位并保留历史坐标；盲区补传应保持事件生成时间。
时间精度仍取决于最近有效 GNSS/NTP 校时及设备时钟漂移。
