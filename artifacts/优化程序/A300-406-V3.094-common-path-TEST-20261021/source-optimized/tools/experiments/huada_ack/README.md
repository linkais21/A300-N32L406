# 华大单帧 ACK 隔离实验

本目录不在生产 Makefile 源列表中，尚未接入设备。没有修改 FOTA、Bootloader、主循环、GNSS ISR、配置或全局编译策略。

实现范围：校验完整 AID 帧、限定消息及长度、发送一次、等待匹配的完整 ACK/NAK、无符号计时回绕、超时、发送失败、显式取消。不自动重发，不持有帧指针，不申请动态内存，不占用 Flash owner。轮询和 ACK 处理不等待；TX 回调仍必须由集成层保证有界。

协议依据：工作区华大 AGNSS 应用指南 V1.4。GPS/BDS 每帧最多五颗星历，分别每颗 65/92 字节；TIME/POS 负载分别 20/17 字节。时间/位置有效性与新鲜度应由上层验证，不属于该 ACK 事务的证明范围。

## 验证

在固件仓库执行 `python -B tools/tests/test_huada_ack_trial.py`。

2026-09-17 结果：最终 host C harness PASS，使用 `-std=c99 -O2 -Wall -Wextra -Werror`。覆盖有效 GPS、最大 BDS、TIME/POS 帧，错误长度/校验/组 ID、空指针、重复提交、错命令 ACK、截断 ACK、重复完成、NAK、截止时刻及迟到响应、uint32 回绕、重复取消、TX 失败。

首次运行失败是新增模块尚不存在导致的编译失败，不是现有生产固件的行为回归复现。扩充用例后一次运行遇到 host GCC 无法启动 assembler 的环境错误，随后同一命令成功。不能把这两次失败称为已复现生产缺陷。

独立 Cortex-M4 硬浮点编译（`-Os -finline-limit=64 -fno-inline-functions-called-once -fstack-usage`，无 LTO）：text 374 B，data/bss 0。状态对象由调用方提供，不能将 bss=0 解读为无 RAM 成本。
`.su`：start 40 B、校验函数 20 B、receive 16 B、poll/cancel 0；这些是单函数帧，不包含 TX 回调、ISR 或整体栈证明。独立对象大小不是最终 LTO 链接增量。

现有 `test_agnss_vendor_stream.py`、`test_agnss_scheduler.py`、`test_agnss_workspace_ownership.py` 均 PASS。`git diff --check` 返回 0。生产源码未变，本实验不声称整机发布门禁或实机通过。

## 接入前必须解决

- UART 中 ACK 与 NMEA 的有界分流及半包/粘包组装；此 API 只接收完整二进制帧。ISR 不能发送下一帧、访问 Flash 或推进 modem 状态机。
- ACK 只有命令组/子 ID，没有星历帧序号。同类型迟到/重复 ACK 在新事务中无法由该模块辨别。集成层需要接收事件边界、处理已排队响应并在超时/取消后终止本次注入，不能立即续传同类型帧；仍需实机验证模块响应时序，不能保证识别任意延迟重复包。
- 测試用 1000 ms 等值是注入的期限，不是已确认模块响应时间；正式期限及恢复策略需根据协议和 HIL 确定。
- 当前生产注入接口的 bool 不能同时表达已接收数据、等待 ACK、完成和失败；应明确接口迁移及缓存偏移推进规则后集成，防止重复注入/跳过数据。
- 取消必须由上层联动释放缓存与共享工作区；实验模块本身无这些资源，取消测试不证明整个设备资源已释放。
- 校验和不是密码学认证。网络下载来源、响应限制、文件有效期和服务器鉴权仍需独立契约。
- 完成剩余 Flash 优化实验、完整链接容量/栈评估和升级争用 HIL 后才能合入。历史仅剩 504 B 的测量不能支撑直接增加完整下载和 ACK 路径。
