# 华大 AGNSS、Flash 优化和 IMEI 对接验证记录

## 当前结论

生产源码已接入华大在线下载及逐帧 ACK，IMEI 元数据已加入 OTA 检查请求。App 和未修改源码的 Bootloader 均编译完成。完整 release-gate 退出 2：全程序栈/堆/中断嵌套证明缺失。没有修改门禁，也没有生成发布包、烧录设备、部署平台或提交代码。

最终 App：`build-huada-imei-hil/a300_firmware.bin`，106376 B / 106496 B，余 120 B。静态 SRAM 18068 B，已知主调用路径 2408 B，剩余 4100 B（尚未扣除未知库帧、堆峰值和 IRQ）。必要的 4096 B 间隙检查通过，但不能代替完整 RAM 门禁。

Bootloader：`build-huada-imei-boot/bootloader.bin`，独立临时 Makefile 仅重定向输出目录，源码和编译选项未变。其二进制包含原有 factory-init 请求区域；不能当作无副作用的普通 App 更新。未发布烧录包。

## 已实施

- `agnss_online.c`/`huada_ack.c`：AGPS 通道 HTTP GET、30 秒事务期限、最长 512 字节响应头、最多 4096 字节星历、拒绝非 200/重复长度/Transfer-Encoding/Content-Encoding/超长/截断；逐帧完整校验后才开始注入，每帧等待 ACK，失败结束本次事务并退避 60 秒。成功后两小时且无定位才重新尝试。
- 使用独立 AGNSS 工作区，不占用 OTA 服务工作区，不新增 8 KiB 下载缓存或 NOR 写入；旧缓存读取模块仍保留。在线失败退避期可使用既有缓存读取路径，该旧路径尚不是新的 ACK 状态机。不能将在线路径验收等同于旧缓存的新鲜度与 ACK 已完善。
- `gps.c`：ISR 有界收集完整二进制 ACK，非 ACK 二进制帧按长度跳过，主循环读取邮箱；ACK 校验和和事务匹配在主循环完成。正常定位时不启动在线注入，不新增强制冷启动，不自动注入无法证明新鲜度的时间/位置。
- `flash_config.c`：新默认配置打开 AGPS；已有持久配置不强制改写。`at_config.c` 支持 `AGPS=ON` / `AGPS=OFF`（以及 1/0），保存失败恢复原值。该入口此前只回复 OK。旧设备若保留关闭配置，需要显式开启。
- `fota.c`：仅检查请求添加可选 `X-Modem-IMEI`，严格 15 位数字，复用原 Range 临时缓冲；不向下载主机发送该头，不打印完整 IMEI。接口路径、deviceId、升级响应、Range/If-Range、签名、BCR、回滚完全不改。
- `ota_platform` 已有该头的接收、首次记录及冲突保护和管理页面展示，本轮无需修改。平台仍要求已登记设备；头字段不用于绕过授权。未操作线上平台。
- Flash：局部单次调用内联，main/FOTA/签名编译单元保留旧编译选项；链接级允许内联，因此最终机器码不能宣称完全相同。合并 UART 无符号格式化转换、F39 解析/回复/SMS 命令名表、车牌省份常量；合并旧控制台相同确认分支。既有日志文本、格式化返回计数及命令权限保持。坐标转换去掉不必要的 64 位舍入，并增加 NaN/范围检查和负海拔的有符号转换。

## 验证与证据

- 99 项脚本通过，详见 `build-huada-contract/validation-final/commands.json`、对应日志和输入摘要。覆盖 GNSS、AGNSS、OTA、Bootloader、盲区、F39/SMS、继电器、EC800M、生产测试、工作模式等。该批后增加“已有定位不启动在线注入”修复及附加用例，`test_agnss_online.py` 已重新通过，最终固件重新链接。
- `test_fota_modem_imei.py`：先出现缺少请求头的实际断言失败，再通过正常、空/短/长/非数字/CRLF、下载不携带及日志不泄漏测试。
- `test_agnss_vendor_stream.py`：先复现越界坐标仍注入，再通过范围/NaN/负海拔/舍入及原流式回归。
- `test_at_config_serial_f39.py`：先复现 AGPS 只回复 OK、不保存，再通过开关保存和失败回滚。其余 F39/SMS 权限、安全动作及旧命令回归通过。
- 新 AGNSS/ACK 模块首次 RED 为接口尚未实现的编译失败，不冒充旧生产行为缺陷复现。
- 平台使用独立 `.venv-ota-review` 和临时数据库，82 项 unittest 通过；无生产数据库变更。最初系统 Python 缺 Flask，已在独立环境安装声明依赖后验证。故障注入日志中的 audit unavailable 是预期测试场景。
- `release-guard`、Flash guard、签名信任锚、libc parser guard、必要 RAM 间隙和 Bootloader 静态容量通过。完整 `release-gate` 失败及原始原因保留于 `build-huada-imei-hil/release-gate.log`。
- 曾有 host GCC assembler 路径异常，及测试夹具缺新接口/链接源、两个继承夹具的未使用辅助函数错误；分别修正环境或测试夹具，未删生产校验绕过失败。
- 2026-09-17 实际 HTTP 读取：3376 B，8 个 BDS F1 D9 帧，全部长度/校验正确；响应文件和头在 `build-huada-contract/`。此观测不保证未来内容新鲜度或在线状态。
- `git diff --check` 返回 0。针对本轮快照核对：Bootloader 源码不变，FOTA 源码差异严格限定在 IMEI 请求头生成分支。

## 尚未完成的验收

完整静态运行期证明、设备连续运行、UART ACK 时序、NMEA/调制解调器数据不丢失、升级与 AGNSS 争用均需要实机/HIL 验证。ACK 无帧序号，对同命令迟到重复包仍有协议歧义；超时/取消终止本轮，不立即重传。

线上星历的完整性校验不是来源认证或有效期证明。当前在线模式取得即时响应后使用，不将响应持久化；HTTP 文件的生成时间及星历自身时效还需验收。指南中的冷启动、可信时间/位置注入没有被无条件加入，以免中断已有正常定位；实际 TTFF 改善不能从 host 测试推断。

余 120 B 非常紧张，不能作为后续新增功能预算。虽然完整构建已成功，目前不将这些产物标为发布通过或安全烧录交付包。不得上传 OTA 平台供批量升级；待门禁缺口处理、测试版身份及明确 HIL 交付条件落实后再生成独立测试包。
