# A300_406 JT808 身份诊断与 FIP 默认关闭设计

## 1. 目标

解决实机在 EC800M 已获取 IMEI/ICCID 后仍持续打印 `identity invalid`、未发送 JT/T 808 `0x0100` 的问题；增加每次开机一次的完整身份和服务器诊断；新设备与恢复出厂配置默认关闭副服务器，同时保留升级设备已经持久化的 FIP。

## 2. 已确认事实

- EC800M 已进入 READY，主、副 TCP 均能建立连接。
- JT808 在 `terminal_identity_sync()` 返回失败后停止注册，因此问题发生在身份格式检查、PID 持久化或写后校验阶段，而不是平台应答阶段。
- 当前实机健康日志显示最小栈余量约 344 B。
- PID 首次持久化调用链同时存在多份 `device_config_t`、完整 v3 槽缓冲和 Flash 校验缓冲，存在栈溢出风险。
- 当前 v3 配置只有 `backup_ip/backup_port`，没有区分“历史默认值”和“用户 FIP”的来源字段。

## 3. 身份与诊断设计

设备身份继续遵循已确认的 JT/T 808-2013 规则：PID 为 11 位十进制数字；PID 为空时从精确 15 位 IMEI 的末 11 位派生，并在首次 JT808 发送前成功持久化；注册体终端 ID 为 PID 末 7 位。

每次开机在 EC800M 身份读取完成后只打印一次：

```text
[DEVICE] IMEI=<15 digits> ICCID=<full value> DEVICE_ID=<11 digits> JT808_TID=<7 digits> PID_SOURCE=CONFIG|IMEI
[SERVER] MAIN=<host>:<port> BACKUP=OFF
```

若副服务器已配置，则第二行打印 `BACKUP=<host>:<port>`。若身份同步失败，不打印伪造 ID，而打印一次明确原因，并按现有 5 秒有界节奏重试：

```text
[808] identity invalid reason=IMEI_FORMAT|PID_FORMAT|FLASH_LOCK|FLASH_WRITE|VERIFY
```

完整 IMEI/ICCID 是用户明确要求的启动诊断信息，不在周期健康日志、鉴权日志或其他重复路径打印。

## 4. 低栈配置写入

保持 v3 双槽、generation、CRC 和最后 commit marker 契约不变，不修改外部 Flash 分区或磁盘格式。

降低配置写入调用链峰值栈占用：

- 避免在 `terminal_identity_sync()`、`cfg_store_candidate()`、`slot_write_locked()` 和 `ext_flash_write_verified()` 的嵌套调用中同时保留多份大对象。
- v3 记录按固定小块写入和回读校验；CRC 仍覆盖 `version/data_len/generation + device_config_t`。
- 写入非活动槽，最后单独写 commit marker；只有完整回读有效后更新 live config。
- API 返回可观测失败阶段，使 JT808 能区分锁获取、擦写和写后校验失败。
- 所有缓冲固定大小、无动态分配、无 ISR Flash 写入、无无界重试。

## 5. FIP 默认与升级兼容

- `k_config_defaults.backup_ip=""`、`backup_port=0`。
- 无有效配置、新机及恢复出厂时 CH3 为 `DISABLED`，启动日志显示 `BACKUP=OFF`。
- 升级加载任何已有且有效的非空 `backup_ip/backup_port` 时原样保留，包括值为 `808.lhhn.net:8898` 的配置；旧格式没有来源字段，禁止按地址值猜测并删除。
- `FIP,58.61.154.237,7018#` 成功持久化后重置 TCP 管理器并启用 CH3。
- `FIP,0#` 成功持久化后关闭 CH3。
- 地址为空或端口为 0 均视为关闭；不得回退到主服务器地址和端口。

## 6. 测试与验收

先写失败测试，再实现最小修复。自动测试至少覆盖：

- 空 PID + 合法 IMEI 成功持久化并发送注册。
- 身份失败阶段分别可区分，失败不发送 `0x0100`。
- 配置 v3 掉电切点与 v1/v2 迁移不回归。
- 新默认副服务器关闭。
- 已有 FIP 从 v1/v2/v3 升级后保持不变。
- FIP 设置启用 CH3，FIP 0 关闭 CH3，未配置时不回退主 IP。
- 启动身份/服务器信息只打印一次。
- host-C 编译使用 `-Wall -Wextra -Werror`。
- 常规固件、hardware-bringup 固件、release guard 和 RAM guard 通过。

实机/HIL必须验证：首次空 PID 的 Flash 持久化、重启后直接使用 PID、真实 `0x0100/0x8100/0x0102/0x8001`、FIP 动态启停、掉电恢复以及栈水位。

## 7. 非目标

- 不改变 JT/T 808-2013 身份规则。
- 不清除升级设备的已有 FIP。
- 不修改 FOTA HTTP 契约或外部 Flash 布局。
- 不提交、不推送、不烧录、不部署。
