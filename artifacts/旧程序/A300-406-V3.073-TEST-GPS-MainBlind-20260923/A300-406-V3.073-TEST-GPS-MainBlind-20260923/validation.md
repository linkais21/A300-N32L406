# 主平台盲区存储与双连接隔离

2026-09-23 用户确认：主平台断开期间必须存储盲区，副平台继续独立实时上报；副平台断开不得影响主平台，无需为副平台单独保存缺失数据。

## 实现

- 普通定位、工作模式定位/告警及拐点定位仍向在线主、副平台发送，返回结果以主平台发送是否成功为准。主平台离线或发送失败时走原有盲区持久化事务；副平台失败不再单独触发存储。
- 盲区0x0704仅发给已鉴权在线的主平台。主平台不在线时等待，不切换到副平台。消费记录仍要求通道、连接代次、流水号、消息ID及成功结果均匹配；断线/超时保留记录重试。
- 保留原有NOR布局、记录格式、掉电恢复、Flash所有权、事务重试及容量策略，不进行数据迁移。
- IP/FIP配置变更按对应端点重连；另一端连接和代次保留。相同地址配置不会引发不必要重连。OTA期间仍延后控制操作，多个端点请求合并。APN/PDP重启等共享网络操作仍可影响两条连接。
- 实时发送成功沿用现有发送路径判据，不新增每条0x0200的平台应答队列；盲区0x0704仍必须由主平台成功应答才能消费。

## 验证

RED：修改前广播返回值测试违反主平台所有权；修改前补报测试发现主断开后发送转向副平台。

GREEN：32种广播在线/发送结果组合；主离线、副在线每10秒连续3条工作模式定位入队且发送到副平台；副平台不能接收/消费补报；主恢复后补报，错误通道和旧代次ACK不能消费；真实GPS过滤器+JT808普通定位/告警/拐点线格式；IP/FIP真实命令链的重连掩码；双端点隔离及OTA延后；工作模式调度；NOR存储掉电及补报重试/ACK mutation。

执行入口：test_jt808_broadcast_result.py、test_blind_zone_ack_channel.py、test_blind_zone_replay.py、test_blind_zone_store.py、test_corner_blind_zone_replay.py、test_gps_report_wire.py、test_tcp_endpoint_isolation.py、test_tcp_manager_fip.py、test_f39_config.py、test_f39_end_to_end.py、test_work_mode_policy.py、release_guard.py。上述检查通过。

独立构建目录 build-blind-main-20260923，Flash 104624/106496 bytes，静态RAM17252 bytes，已通过ARM构建和Flash门禁。候选保留当前V3.073标识，不是正式新版本。

未通过项：ram-guard缺少全程序栈/堆/异常上界证据；test_at_config_serial_f39.py原有OK断言失败；test_work_mode_jt808_contract.py旧源码形状断言失败；test_jt808_dual_session.py旧无定位拒绝断言失败。后两项已用本次修改前jt808.c隔离复现，未放宽断言；AT失败与之前诊断一致。不能据此声称全部回归通过或发布就绪。

需要实机/HIL：10秒间隔主断副在线、主恢复收到0x0704并正确ACK；副断主持续实时上报；双方断开及设备掉电恢复；实际IP/FIP改址只断开对应链路。此候选尚未烧录，不自动替换当前用户正在验证的固件。
