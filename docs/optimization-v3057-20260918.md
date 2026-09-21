# V3.057 优化整合与 HIL 交付

## 合入范围

以 V3.056 稳定性测试包为对照，整合当前工作树中已实现的两项优化：

1. STR-01：`include/debug_uart.h` 提供日志分级；`src/jt808.c` 三处、`src/mileage.c` 一处高频日志默认关闭，可用 `DBG_LOG_LEVEL=2` 恢复。关闭时仍求值参数。命令结果、异常及其他日志保留。
2. LIBC-01：`src/syscalls.c` 自有 `exit()` 转入原有 `_exit()`，不引入 libc 的 stdio 清理状态；保留 `_sbrk` 的链接器堆边界检查。最终 ELF 无 `__sf`、`__sinit`、`__call_exitprocs`。

这两项此前已在工作树，本轮保留并统一版本验证，没有重复重写。相对旧包源码哈希，业务代码差异仅上述三个 C 文件及日志头；版本头/config 另有身份更新。未采纳 double 转 float、整数高程替代或 `-finline-limit=32`；默认保持 64、堆预留不变。

身份更新为 V3.057、计数器 3057，使用生成器刷新北京时间。更新 `release_identity.json`、`include/build_version.h`、`include/config.h`，同步身份测试和 `tools/release_guard.py` 的已审查身份文件哈希，保留全部拒绝逻辑。

## 验证

证据位于 `build-v3057-optimization-20260918/`；交付包另附 validation、source 和文件 SHA-256。

- 34 个相关 host 测试脚本最终通过：身份/时间戳、日志与堆边界、构建恢复、发布清单/栈门禁、信任锚、JT808/NMEA/里程、盲区/Flash、FOTA/AGNSS、Bootloader 契约。
- 身份测试先在 V3.056 下确认 RED，再更新 V3.057 后通过。
- 堆边界测试首次卡在主机退出：固件自有 `exit` 覆盖主机 CRT。夹具现对 `exit` 重命名，编译/运行增加超时，upper/lower/mixed 回归通过；未更改固件逻辑。已清理该次测试进程。
- 构建恢复夹具首次因缺少版本生成器失败。现复制版本头并用 `make -o include/build_version.h` 固定身份，防止时间戳刷新掩盖缺失产物重建；8 种串行/并行恢复场景通过。初始失败及修复后日志均保留。
- App 与 Bootloader 使用各自现有 Makefile 独立目录构建，无编译警告。Bootloader 仅使用输出目录替换覆盖文件，未修改其源 Makefile；首次临时覆盖误替换 `build_version.h` 路径，修正为完整词替换后构建通过。
- App Flash 106160 / 106496 B，余 336 B；静态 RAM 17756 B；已知 main 调用链帧和 2408 B。旧 V3.056 包为 106176 B / 18068 B；交付产物净差为 Flash −16 B、静态 RAM −312 B，不冒称为单项独立 A/B 收益。
- release-guard、平台信任锚、Flash 检查、libc parser 检查、Bootloader 静态容量检查通过。
- **完整 release-gate 失败**：ram-guard 报整程序栈证据不完整（76 缺失帧、52 间接跳转）。未扣堆/IRQ/未知帧前剩 4412 B，不等于安全运行余量；`release_approved=false`。
- 最终 ELF/BIN 检查确认 V3.057 身份、stdio 清理符号消失、4 条完整 verbose 格式串消失、命令结果日志保留。

本轮额外修改仅版本/身份校验、两个测试夹具和本文。原有默认固件、旧交付包保持原样。未提交、推送、部署或烧录。

## 交付边界

输出 `artifacts/A300-406-V3.057-Optimization-HIL-20260918/` 及同名 ZIP，包含 App/Bootloader/Combined 的 HEX/BIN、ELF/MAP、验证和源快照。仅为 HIL 测试版，不生成 OTA 平台发布包，不绕过正式发布脚本的 gate。

Combined HEX 自带地址；Combined/Bootloader BIN 为 `0x08000000`，App BIN 为 `0x08006000`。**完整烧录 Combined/Bootloader 后，既有出厂初始化会清除外部 Flash 的配置、BCR、OTA 断点及授权记录，应先保存参数。** 本轮没有执行烧录。

需要实机/HIL 验证：启动版本和复位原因、JT808 双通道与命令回复、里程持久化、AGNSS/OTA 争用和恢复、ACC 休眠唤醒、24 小时稳定性、栈水位/堆峰值及中断嵌套。日志减少的实际耗时收益尚未测量。
