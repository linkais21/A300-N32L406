# GPS/URC 第二阶段栈优化设计

## 证据与目标

第一阶段 HIL 将 `STK_PEAK` 从 4436 B 降到 2572 B。全量 ARM GCC 栈审计显示项目自身函数已明显收敛，但 GPS UART4 ISR 仍在完整 NMEA 到达时直接调用 GGA/RMC 解析，其中使用 `atof/strtod`；EC800M URC 还使用 `sscanf/vfscanf`。这些 libc 深层调用不会由应用源 `.su` 完整呈现，是剩余峰值的首要根因。

目标是让 UART4 ISR 仅收字节和交接完整句子，并移除在线主链路的通用 scanf/浮点字符串转换器，同时保持 GNSS 与 4G 行为兼容。

## 设计

- GPS 使用两个静态 NMEA 槽。ISR 写当前槽；完整且未占用时发布，随后切换槽。两个槽均待处理时丢弃新句并计数，绝不覆盖主循环正在解析的数据。
- `gps_process()` 每次最多消费一个已发布句子，执行 checksum、GGA/RMC 解析和状态更新，使主循环保持有界。
- 新增有界十进制解析器，支持可选符号、小数点和有限数字；用整数缩放计算经纬度、速度、高度、HDOP，拒绝多小数点、空字段和溢出。
- EC800M 使用前缀匹配和有界十进制整数解析替换 QIOPEN、QIURC recv/closed、CSQ 的 `sscanf`。格式错误不得改变通道或信号状态。
- 栈门禁增加 GPS ISR、GPS 主循环解析和 URC 处理目标，并用构建/链接证据禁止应用重新依赖 `sscanf`、`atof`、`strtod`。

## 验收

- ISR 不解析 NMEA；连续 GGA/RMC、半包、校验失败、队列满和数值边界有 host 回放覆盖。
- 有效 NMEA 的定位、时间、速度、方向、高度、HDOP 与原协议含义一致。
- QIOPEN、QIURC recv/closed、CSQ 的成功与畸形输入行为受测试保护。
- 应用构建不再链接 scanf/strtod 路径；release、RAM、stack guards 通过。
- HIL 必须确认 GNSS 定位、AUTH/ONLINE 与 HEALTH；不以 host 测试代替实机结论。
