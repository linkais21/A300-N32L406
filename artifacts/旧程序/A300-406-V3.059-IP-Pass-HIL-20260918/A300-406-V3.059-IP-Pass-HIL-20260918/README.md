# V3.059 IP/FIP 与日志平台 Pass 烧录测试

用户已确认日志平台一次性配置为 `Pass: "hbt,120#"`，并要求生成烧录测试固件。本版是 HIL 候选，不是生产发布版；未连接或烧录真实设备。

## 修复范围

- 0x8103 的 0x0018 只修改主端口，保留独立 FIP 端口；短信 IP/FIP 仍走既有独立设置入口。
- UDP 使用 OTA 临时通道和既有 AT 所有权，拒绝占用中的通道，不强行关闭 OTA。等待真实 QIOPEN 成功后发送，主循环分步等待应答，有界 QIRD 读取二进制数据；SMS 正文不能伪造 UDP 应答。
- IMEI BCD 最高半字节补 0；严格校验响应头、命令、设备身份、长度、校验、尾字节和 Pass 字段。接收容量 384 B，满足单个最长 255 B 字符串的完整响应，并低于 QIRD 512 B 内部缓冲约束。
- 支持一个字符串 Pass，内容复用 F39 执行器；可带一层双引号及末尾 #。多个参数用 DUALSET，支持指令表的冒号分隔语法。未知字段、尾部额外数据、错误配置标志、执行/保存失败不发送成功确认；无待配置时也不发送 0x14。
- 在线且未进入 STOP1、FOTA 空闲时，每 60 秒发起配置查询；无响应最多尝试 3 次，之后退出本轮。配置处理中暂缓 STOP1。
- DUALSET 改为一次解析写入私有候选；整组验证通过后才提交，失败仍恢复候选并清除副作用。没有删除校验或安全条件。

静止坐标漂移算法和阈值没有修改。V3.058 诊断已证明未锁点；本版仍保留 GPS-DRIFT 诊断，不应将本包描述成漂移修复版。

## 自审与验证

原先的“配置生命周期测试通过”只覆盖假响应，没有证明真实 UDP 收发；上一轮的空配置成功确认、弱链接执行器和不完整字段校验已修正。本轮增加三层证据：参数帧拒绝路径、真实 F39 持久化/定时器联测、完整 EC800M UART/URC/QIRD 收发（含二进制 NUL/换行/OK、SMS 伪造 URC 拒绝、超时）。所有测试只在 host 运行。

48 项定向回归及各自命令/退出码随包保存到 validation。包括配置、UDP、AT 接收、短信、F39、JT808 主副会话、IP/FIP、继电器拒绝路径、STOP1、GPS 报文、版本/Flash 布局及信任锚。构建有 Flash 硬容量门禁，不扩大链接分区。

App 使用独立构建目录，参数为 `SIZE_FLAGS=-Os -finline-limit=128`（保留 LTO、硬浮点和安全代码），未更改默认 Makefile。消除 DUALSET 重复解析、合并 UDP 状态后，该参数下 Flash 使用 106476/106496 B，剩余 **20 B**。多种更早参数试验超限，日志保留在工作区证据目录；只有最终通过容量检查的镜像进入测试包。

身份门禁变更经过与 V3.058 快照比较：main 仅新增周期查询条件；config/build_version 仅版本与时间戳变化，随后更新审核哈希。release-guard 通过。Bootloader 从当前源码在独立 staging 目录构建，未复用未经比对的历史固件。

完整 release-gate **未通过**：缺少完整栈/堆/异常边界证据。当前静态 RAM 17772 B、已知调用帧 2528 B，尚余 4276 B 未扣除堆/IRQ/未知帧，不能等同于运行内存安全证明。release_approved=false；本包仅用于用户授权的专用设备烧录测试。

## 现场测试顺序

1. 保存现有参数。Combined 含出厂初始化请求，首次启动会清除既有配置、BCR、OTA 断点及授权记录，需要重新配置设备。
2. 用 N32L406 对应 SWD 工具烧录 Combined HEX（内含地址），下载后执行校验、复位。BIN 的起始地址为 0x08000000；不要使用 N32G452 目标。App-only 不能替代 Combined 的首次初始化流程。
3. 调试串口 115200/8N1，确认 App 显示 V3.059。恢复 APN、平台地址及必要身份/授权参数。
4. 设备在线后在平台设置一次性字符串 Pass，先测 `hbt,120#`，保持设备唤醒，观察约 60 秒内查询（如网络超时可能更久）。检查平台状态、串口 `[CFGQ] result=0`、`HBT#` 返回 120，并复位后再次查询。result=0 也可能表示平台无待配置，必须同时核对值和平台状态。
5. 测试 `FREQ,30,180#` 及 `DUALSET,HBT:120*FREQ:30,180#`；分别通过短信 IP 和平台 0x8103 改主端口，确认 FIP 未变。
6. 收集配置期间断网/超时、STOP1 唤醒、主副平台重连和 HEALTH 栈水位日志。固定/低速移动的漂移对照仍需另测，保留完整 GPS-DRIFT。

## 本轮文件

行为：src/cfg_query.c、src/ec800m.c、src/main.c、src/work_mode_sleep.c、src/f39_command.c、src/f39_config_adapter.c；沿用本会话 src/jt808_params.c 和 include/jt808_params.h 的端口修复。

验证/文档：新增 test_cfg_query_pass.py、test_cfg_query_f39.py、test_ec800m_udp_transaction.py、test_ec800m_udp_wire.py；更新 test_cfg_query_lifetime.py、test_cfg_query_contract.py、test_release_identity_contract.py、tools/release_guard.py 和本说明。版本文件：release_identity.json、include/build_version.h、include/config.h。

未提交、推送、部署或操作生产设备。所有硬件行为**需要实机/HIL 验证**。
