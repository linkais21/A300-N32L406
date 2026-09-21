# A300 V1.5.0 联调 Fix5：华大 GSV 输出与双频解析

保留 Fix4 的全部固件功能和优化，继续使用原 A300ProductionTester.exe V1.5.0，TTS/RS485 不测试。没有创建分支、提交或烧录设备。

## 证据与修复

2026-09-17 15:09 的用户日志显示 RX 从 106595 增至 109979，GGA/RMC 各从 369 增至 381，GSV/COMPLETE 始终为 0；QUEUE_DROP 从 62 增至 67，LENGTH_DROP/CHECKSUM/OVERRUN 为 0。说明解析器没有得到有效 GSV；不能单凭此日志把原因全部归结于队列或模组。原始日志留在本地，不随包附带真实轨迹。

资料冲突：旧 AGENTS 副本及旧源码把 TAU804M 与 CASIC 的 PCAS03 配置关联；华大原始《T-5-2204-ALLYSTAR GNSS 接收机二进制协议规范 V2.3.6》第 1.3 节、第 5.4.2 节（58–59 页）规定以 F1D9 CFG-MSG 配置输出，NMEA group=F0，GGA=00、GSV=04、RMC=05。按协议原文修正初始化/唤醒配置，每个周期设为 1，仅发送易失设置，不写模组永久配置。发送保留有界超时，失败打印 CFG-MSG TX failed；尚未实现二进制 ACK 确认，不把 UART 发送完成等同于模组配置已生效。

仓库提供的“华大单北斗双频模组_NMEA-0183数据.txt”中，BDGSV 是 8 页/28 条观测，第 6 页仅 1 组，第 7–8 页切到 signal=9。旧解析器强制页数=ceil(星数/4)，且拒绝中途换频点，因此必然拒绝该真实格式。现按各页实际字段数处理带 signal ID 的 GSV；顺序/总页数/星数/校验/过期仍校验。跨频点分页仅累计首频点 C/N，其他频点推进完整周期但不重复计星。独立交错频点不能替换选中的周期。

## 烧录与验收

1. 保存设备参数。烧录完整 SWD-Combined-N32L406CBL7.hex；若使用 BIN，地址为 **0x08000000**。写后校验并复位。完整镜像首次启动会重置配置/升级状态，需重新写入参数。App 地址为 0x08006000，不能将完整 BIN 写入此地址。
2. 保持卫星接收条件，用原 V1.5.0 工具测试。检查 GPS 的有效 CN 星数、CN 平均/最大从 0 更新为实测值，并满足原来的门限与连续样本要求。不降低门限、不用总星数冒充 CN 星数。
3. 如仍未通过，断开工具串口，在解压目录运行以下命令，等待 15 秒。日志保存在 diagnostic-logs 新文件中：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\capture_production_diag.ps1 -Port COM12
```

GNSSDIAG 的 GSV 应增长、COMPLETE 应增长；结合 QUEUE_DROP 判断是否仍有接收调度问题。原始语句输出最多 32 条/5 秒，位于 MCU 接收队列之后，并非 UART 无损抓包。日志可能含真实位置，分享前脱敏。

## 验证及限制

新增真实 C 回归：修复前配置字节测试失败、华大 GSV 样例质量测试失败；修复后通过。覆盖初始化/唤醒的 CFG-MSG ID/周期/Fletcher 校验、有界发送失败；双频真实样例、缺页、重复页、坏 CN、过期、主频点去重。相关回归和构建结果见 validation。

GPS 模组接受配置、实机 GPS 通过、唤醒恢复、真实串口队列负载均需要实机/HIL 验证。未修改 UART 队列大小或虚报 CN。完整发布门禁仍因全程序栈/堆/异常上界证据不完整失败；test_terminal_identity.py 仍有既有测试夹具依赖链接失败。本包为样机测试候选，不是已批准量产版本。

本轮变更：src/gps.c；tools/tests/test_gps_huada_output.py、test_gps_huada_gsv.py；本文、生成的 include/build_version.h 和新交付包。原 EXE、订单、配置、测试记录及已有用户修改保留。
