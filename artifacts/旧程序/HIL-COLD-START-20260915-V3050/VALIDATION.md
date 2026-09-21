# V3.050 冷启动修复交付

交付：artifacts/HIL-COLD-START-20260915-V3050。使用其中 SWD-Combined-V3050.hex，详细连续上电方法见包内 README。

依据是 V3.049-RETRY 实机停在镜像选择返回后的恢复循环，启动 BCR 缓冲区残留为零、稍后不复位只读 NOR 双槽为 FF。改动修复已观测失败的有界恢复路径，同时强化 SPI 事务结束与片选时序；不声称首次读零的底层诱因已通过独立硬件实验完全证明。

## 实际触碰文件

- bootloader/src/bcr.c：在原有用户三次紧密重读基础上改为最多 20 次、有间隔的双槽重读，含 I/O 失败；保留 fail closed。
- bootloader/src/platform_n32l406.c：CS 建立/保持/间隔、BSY 有界等待、BCR ID 门控及重试等待。
- bootloader/src/main.c、boot_progress.c、include/bcr.h、include/image_install.h：启动状态与重试 UART 日志，复用有界 UART 输出；不变更 Flash 格式、分区和 OTA 契约。
- bootloader/Makefile：启动版本头变化触发 main.o 重编译。
- tools/tests/test_boot_cold_start_recovery.py、test_boot_spi_timing.py、test_boot_bcr_device_gate.py：新增生产 C 故障注入/时序/身份测试。
- tools/tests/test_bootloader_bcr_failclosed.py、test_bootloader_platform_contract.py、test_boot_progress_uart.py：同步新内部接口，保留拒绝路径；瞬态错误场景确认读取到较新 Pending 而非误使用旧 Trial。
- release_identity.json、include/config.h、include/build_version.h、tools/tests/test_release_identity_contract.py、tools/release_guard.py：版本 3050 与规范化指纹同步，仅刷新两个版本文件指纹，不放宽规则。
- 本文、专项计划、交付目录与本轮 build/cold-start-3050 工作文件。原有业务代码与旧交付包保留。

## 验证与审查

新冷启动测试在修改前失败：连续读零或 I/O 错误后无法进入 App；修改后 9 个正常/瞬态/持久错误/最后一次恢复/较新 Pending 遮挡场景通过，且无擦写。SPI 旧实现未满足片选间隔，修改后 CS/BSY/TE/RNE 超时通过。

56 个相关脚本首轮 54 通过；frame-budget 漏传参数、identity 版本指纹未更新的两个失败已分别用正确参数和新指纹重跑通过。保留首轮记录，不能把首轮称为全通过。

App `make -B all BUILD=build/cold-start-3050/app` 成功，无编译警告；Bootloader 最终通过独立 boot-hil.mk 和正确绝对工具链路径构建，无编译警告。早期 make/工具链路径失败未作为成功证据。最终命令保存在 validation。

`make release-gate BUILD=build/cold-start-3050/app` 退出 2：release-guard 通过，RAM gate 因全程序栈证据不完整拒绝。单独 frame-budget、libc-parser、平台信任锚及 Boot 静态容量检查通过。RAM/栈风险延续自 V3.049，HIL 包保留 release_approved=false。

按 requesting-code-review 技能执行范围内自审：确认重试只读、两槽失败不能降级使用旧记录、次数有界且喂狗、持续损坏仍拒绝、UART 卡住只禁用日志不阻塞启动、无分区/签名/型号/地址变更。没有独立代理审查，未声明其存在。启动重试期间不会重复工厂擦除、试运行计数或安装；20 次耗尽后明确输出恢复状态并保留故障现场，不无限重启。

需要实机/HIL 验证：至少 50 次真实冷启动、首次初始化、真实 SPI 时序、Boot 跳转与 OTA 恢复。此次未烧录、未提交、未推送、未上传平台或部署。
