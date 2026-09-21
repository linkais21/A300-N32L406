# V3.060 参数修复烧录验证包

2026-09-18。本次已解除 `2026-09-18-field-config-findings.md` 中的链接容量阻塞，交付 `artifacts/A300-406-V3.060-FieldConfig-HIL-20260918.zip`。版本为 `T360-A300_406_20260918174645,V3.060`，计数 3060。

## 容量与源码

App 106380 / 106496 B，剩余 116 B；App、Bootloader 构建无警告，Flash 检查通过。未扩大 Flash 分区、删除日志、安全校验或功能。实验中无收益的编译参数及 ECC 优化级别变体没有进入交付。

本次在前轮参数修复基础上实际调整：

- `Makefile`：加入共享编码模块，默认内联阈值 64 → 128，保留 main/FOTA 单次内联限制。
- `include/plate_encoding.h`、新增 `src/plate_encoding.c`：将重复车牌表和转换函数改成共享实现。39 项省份映射通过 Python GBK 编码独立核对。
- `src/f39_config_adapter.c`：复用同一省份表，合并六个数字命令的共同解析，保留范围、持久化与副作用。
- `src/at_config.c`：初始化与刷新共用实时信息快照；以有界 uint16 解析替代 atoi。旧串口数字参数中的空值、负号/正号、空格、尾随垃圾和溢出现在拒绝，不会修改 TIMER 配置；合法值和原有最小间隔钳制保留。
- `release_identity.json`、`include/config.h`、`include/build_version.h`、`tools/release_guard.py`、`tools/tests/test_release_identity_contract.py`：版本和已审核的身份摘要更新。
- 新增 `tools/tests/test_console_numeric.py`，扩大 `test_car_reply_encoding.py`；以下测试入口补充共享编码模块：`test_at_config_serial_f39`、`test_at_config_handoff`、`test_blind_zone_replay`、`test_f39_config`、`test_f39_dualset`、`test_f39_end_to_end`、`test_f39_actions`、`test_fota_key_config`、`test_jt808_boot_terminal_info`、`test_jt808_dual_session`、`test_jt808_first_location`、`test_jt808_text_command`、`test_sms_work_mode_commands`、`test_terminal_identity`、`test_cfg_query_f39`、`test_jt808_params_wire`、`test_gps_report_wire`、`test_relay_sms`。
- 生成脚本和试验日志在 `build/field-config-release/`；本报告及新交付目录为本次新增文件。保留既有未提交修改，没有提交、推送、部署或烧录。

## 验证证据

77 个相关脚本中 76 个最终通过。旧串口数字拒绝测试先在旧实现触发断言失败，再在新实现通过。两个测试入口最初缺少共享模块导致链接失败，已补齐并重新通过，原失败日志保留。

`test_at_config_handoff.py` 的 O0 子项通过，主机 LTO 子项因 GCC 没有 LTO 支持失败；另行执行 O0/Os 并发交接补充测试通过，不能替代 LTO 运行验证。ARM 固件自身的 LTO 构建成功。

`release-guard`、平台信任锚、Flash 硬门禁、Boot 静态 RAM 检查及镜像结构检查通过。完整 `release-gate` 退出 2：整程序栈/堆/IRQ 证据不完整。App 静态 RAM 17716 B，已知调用帧合计 2536 B，未计 heap/IRQ/未知路径前剩余 4324 B；缺失帧 73、间接转移 56、尾转移 131、环 1。Boot 静态检查不代表其运行栈已验证。

包内 App/Boot/Combined HEX 均从对应 BIN 生成，避免 ELF 导出的稀疏 HEX 与 BIN 对齐间隙填充值不同；已逐地址核对 HEX 校验和、地址、BIN 一致性，核对向量、工厂初始化记录、合并偏移和版本。包内 `source-hashes.json`、`validation/` 和 `MANIFEST.json` 保存当前构建输入、命令/退出码与产物 SHA-256。ZIP 已执行完整解压校验。

## 使用与未完成验收

选择 `SWD-Combined-V3060.hex`（自带地址），或者同名 BIN 从 0x08000000 烧录。**合并镜像首次启动清除配置 A/B、BCR、OTA 断点和授权状态；先记录设备参数，启动后恢复所需配置。** App 单独镜像地址 0x08006000，仅适用于兼容 Bootloader 和状态，不能作空片完整镜像。

`release_approved=false`、`hardware_verified=false`。需要实机/HIL 验证 PID/FIP 双平台应答、APN/PDP 重连和参数保持、粤字显示、精确 `FREQ,10,60#` 下发/回读/实际报文间隔，以及定位、休眠、看门狗、栈水位和长时间运行。精确 APN/FREQ 指令在主机真实 C 链路通过，但现场失败尚未完整复现，不能宣称四项现场问题已全部闭环。
