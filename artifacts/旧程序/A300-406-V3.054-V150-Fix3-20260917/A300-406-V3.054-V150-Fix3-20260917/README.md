# A300 V1.5.0 联调 Fix3（2026-09-17）

本包包含先前优化及 Fix2 修复；继续使用原 V1.5.0 EXE。未创建分支、提交、推送或执行烧录。

## 本次修复

- 允许旧工具把 `APN,AUTO,,#` 读回后写入；仍拒绝 AUTO 模式的非空用户名/密码，以及多余参数。手动 CMIOT 模式保持支持。
- SIM 状态字段经用户确认是 **6F**。原报文只发 `6F:0`；现发送 `6F:0,<真实ICCID>,,`。无有效 20 位 ICCID 时为 `6F:1,,,`。IMSI、OTA ID 未实现查询，保持空字段；不伪造数据。状态以当前有效 SIM 身份为依据，不代表已验证热插拔检测。
- 实际定时/ACC/告警上报使用 `jt808_send_location_work_mode()`，旧代码断网直接返回，未调用盲区 FIFO。现在有效定位或可信历史定位在断网时落盘，BUSY/PENDING/IO_ERROR 保留同一记录，确认提交后才完成调度动作。恢复联网时先完成已有写入，避免丢失或替换旧记录。
- 普通位置报告原有未初始化 event_id；改为统一分配非零事件 ID，并从恢复后的最后记录继续，避免重启后首条与旧记录误判重复。Flash 格式、分区和 9900 条容量不变。
- 正常 `make all` 刷新编译时间。启动行显示 `A300-T9 / T360-A300_406_YYYYMMDDHHMM,V3.054`；Build 行显示同次编译时间。PARAM/OTA 的发布身份及版本计数保持 V3.054，不用设备联网时间冒充编译时间。

## 烧录和验证步骤

1. 使用本包 `SWD-Combined-N32L406CBL7.hex`；若用 BIN，地址 **0x08000000**。两者选一，执行写后校验并复位。完整镜像首次启动会重置配置及升级状态，先保存参数，启动后重新写入。
2. 使用原 V1.5.0 工具，串口 115200/8N1，预期版本 V3.054，TTS/RS485 不勾选。读取参数，再写入测试；APN AUTO 或 CMIOT 均应成功。服务器测试行的预期端口必须与上方写入端口一致（截图测试行 10000、写入框 9999 不一致，应按实际平台设置同步）。
3. 上线后检查日志平台原始报文及解析，6F 应含本机真实 ICCID。现有日志发送前提为 JT808 已上线、CSQ≥6、FOTA 空闲；首次上线触发，常规定时约 10 分钟。断网时不保证实时上报 SIM 异常，仍需平台现场验证。
4. 盲区验证先在有 GNSS 定位、ACC ON 下运行，保持设备电源和 GNSS 接收，切断网络（不能断设备电源或一并屏蔽 GNSS），至少等待两个配置上报周期。串口出现 `[BZ] work report stored` 才表示已获存储提交确认。
5. 恢复网络，观察 0x0704 补报和正确平台 0x8001 成功 ACK。可在断网存储后仅复位设备再联网，验证记录恢复；**不要重新烧录完整包代替复位**。没有有效定位且从未保存可信定位时，不应伪造坐标落盘。
6. 串口启动时间应与本包 MANIFEST 的 build_stamp 一致，而非旧的 20260823000000。

## 验证与剩余限制

RED→GREEN：AUTO 空字段写入、实际 work-mode 断网未调用存储、6F 不含 ICCID、旧构建时间格式均有回归。真实 C 测试覆盖无定位、历史定位、重连途中、写入忙/挂起/I/O失败、事件ID重启恢复；NOR 模拟、掉电切点、FIFO、补报 ACK 及跨平台约束回归通过。原 V1.5.0 EXE 的分包/收包过滤/解析回归保留。
验证命令、退出码和最终镜像清单见 validation 与 MANIFEST。源码发布门禁已针对启动显示变更作有界审查：仅新增 12 位编译时间宏白名单并更新 main 消费函数摘要；版本/型号/计数检查不删除。
另行运行 `test_terminal_identity.py` 仍因既有测试夹具缺少 `service_workspace_try_acquire` 等依赖而链接失败（此前 V3.054 记录已有同类失败）；未将其计为通过。当前真实 JT808 双会话回归和 release_identity_contract 通过，不能替代该未完成的夹具检查。
完整 RAM/栈门禁仍因缺少全程序栈/堆/异常上界证据失败，包为样机测试候选，不批准量产。真实 Flash、电源、网络、GNSS、平台 6F 解析及真实工具全流程均**需要实机/HIL 验证**。旧版 SOS 日志判据等未在本次取得完整实机验收。

## 本轮文件

固件：src/f39_config_adapter.c、src/jt808.c、src/blind_zone.c、include/blind_zone.h、src/log_platform.c、src/main.c。
构建：Makefile、gen_version.ps1、tools/build_dev_release.py、include/build_version.h（生成）、tools/release_guard.py。
测试：test_at_config_serial_f39.py、test_jt808_dual_session.py、test_blind_zone_store.py、test_blind_zone_replay.py、test_terminal_identity.py（同步新增 API 桩）、test_log_platform_wire.py、test_build_version_refresh.py。
其他用户修改保留；现场 EXE、配置、orders、records 未改。
