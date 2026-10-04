# V3.065 OTA 升级成功上报

用户本轮确认：静止时坐标锁定功能 PASS。本轮未修改 gps_report_filter、Gsensor 参数或锁点门槛；这不扩展为所有运动、低速挪动场景均已实机通过。

## 行为与平台契约

版本为 `T360-A300_406_20260919165648,V3.065`，versionCode=3065，deviceModel=A300-406。目标是用户指定的 Python `ota_platform`，POST `/api/device/updates/progress`，沿用 `X-OTA-Token`。本轮不修改平台，不推送、不部署、不烧录。

- 下载后继续上报 downloaded。完成验签后，新增一个独立主循环阶段，把带完整令牌的下载 URL 持久化，再提交 BCR PENDING；每轮最多新增一次 sector erase。
- 新程序运行到既有 30 秒健康确认点，且 TRIAL 的版本与运行版本一致，才提交 ACTIVE 并执行原有确认重启。
- 联网后，只有 ACTIVE、运行版本、断点记录版本和 BCR 包体长度一致，且记录 URL 同源、令牌合法，才上报 success、100% 和完整 OTA 包字节数。
- 等到完整合法 HTTP 响应头且状态为 2xx，才提交断点 tombstone。失败、断线、超时、Flash 清理失败均保留待报记录；成功上报路径不会重启设备。
- 每轮最多 3 个 15 秒窗口，间隔 60 秒；之后恢复普通检查。下一次 6 小时检查周期或设备重启重新获得补报预算。服务器 48 小时令牌有效期保持不变，过期不能补报成功。本实现只有一个待报任务；新任务开始下载会替换旧记录，不是无限结果队列。
- 诊断日志为 `[FOTA] success ack=1 clear=1`；ack 表示收到 2xx，clear 表示本地清理提交成功。日志不输出令牌。

## 持久化与兼容

复用原 0x102000 / 0x103000 双槽，format=1、208 字节记录、CRC、sequence、最后提交 marker 及地址不变；Bootloader、BCR、授权记录格式均未修改。

最终待报记录 offset=0、running_crc=0xFFFFFFFF，避免把向下对齐的断点配上全包 CRC。若在 PENDING 提交前掉电，旧程序可从零重新下载；PENDING 后由 Bootloader 安装恢复。原有中途断点仍保留 sector-aligned offset 与对应 CRC。

V3.064 的 `/d/<token>?d=...` 记录已经保存令牌，升级到本版可恢复并上报本次升级成功。旧查询参数 `?token=` 地址的令牌已被旧版剥离，不能从缺失信息恢复；新版本下载时完整保存这类最终 URL。此处不伪造令牌、不改平台任务为成功。

为容纳新增逻辑，仅在 OTA 范围去重：端口/状态请求格式、token 字符扫描、重试释放代码，以及两类 journal 的擦除→正文→marker→读回比较。BCR CRC 原本不覆盖 CRC/marker 字段，去掉了无意义的临时副本；字段和校验范围不变。shared journal helper 保留 CRC、读回比较及记录有效性检查。

## 验证与限制

证据位于 `build/ota-success-20260919/`，包括每条命令和退出码、日志、源码快照/哈希及本轮 patch。

- RED：用进入本轮前的实际 C 源码重放已确认升级，断言需要 POST 时得到 GET，正确复现原缺口。另新增畸形 `HTTP/1.1 201X` 响应不得清理记录的失败回归，并修复后验证。
- 32 项相关 host 测试脚本通过：新增 success、完整下载→持久化→PENDING、TRIAL 确认、ACK 分片/内联回调、401/500/断线/无响应、三次预算/六小时续报、tick 回绕、Flash I/O/清理失败、错误版本/回滚/同源/无效 token、原 OTA/签名/断点、Bootloader 掉电与恢复、Flash 布局、静止锁点等。
- 既有真实 NOR 1→0/sector erase 的 byte-cut tests 覆盖断点替换、清除、重复掉电、sequence wrap 和授权记录提交；未用纯 Python 状态模型替代实际 C journal。
- 指定平台的 19 项设备协议测试通过。使用生产 C 生成的 success POST，经指定平台 Flask test client 返回 201，临时数据库确认为 success；过期 token 返回 401。测试未连接生产服务，未改生产数据库。
- ARM GNU 14.3.1 App/Boot 编译无编译警告。最终 App 加载跨度 106456 / 106496 B，余量 40 B，仍有 LOW_HEADROOM 告警。静态 SRAM 17720 B，比 V3.064 增加 4 B；已知 main 调用帧和 2536 B，扣除后尚余 4320 B，未计完整堆/IRQ/未知调用开销。
- release identity、签名信任锚、Flash、Boot RAM、libc parser、必要帧预算和范围 diff-check 通过。
- **完整 release-gate 退出 2，未通过**：首个剩余阻断为全程序栈证据不完整（missing frames=68、indirect=67、tail=133、internal=2、cycle=1）。没有豁免或降低门禁；交付仅标记 HIL 候选，非量产发布批准。

范围自审确认：未更改已 PASS 的锁点源码；成功只在 ACTIVE/同版本后发送；失败保留凭据；令牌不输出；提交顺序及资源释放/重试上限保留。未使用独立代理审查。

需要实机/HIL 验证：从 V3.064 通过现有短地址升级到 V3.065，确认版本生效、平台显示升级成功且字节数正确；升级重启期间断网/恢复、状态响应丢失/重启、重复开机、平台令牌过期，以及移动/静止功能无回归。

## 本轮文件

业务：`src/fota.c`、`src/fota_checkpoint.c`、`include/fota_checkpoint.h`、`include/fota.h`。

测试：新增 `tools/tests/test_fota_success_report.py`；更新 `tools/tests/test_fota_platform_flow.py`。

版本：`release_identity.json`、`include/build_version.h`、`include/config.h`、`tools/release_guard.py`、`tools/tests/test_release_identity_contract.py`，身份守卫仅同步新版本对应摘要，未放宽规则。

文档：本文件及 `docs/superpowers/plans/2026-09-19-ota-success.md`。辅助验证和打包脚本、源码快照置于本轮独立 build 目录；候选包单独归档，未覆盖已有产物。
