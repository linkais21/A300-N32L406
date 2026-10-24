# A300-406 V3.092 静止里程修复测试交付

版本：T360-A300_406_20261012100702,V3.092；OTA 版本计数 3092；设备型号 A300-406。
本包包含已验证源码的静止里程修复。已完成软件构建、回归和交付身份验证，实际安装与本镜像实机/HIL 验证待用户测试。

## 交付文件

目录：artifacts/A300-406-V3.092-Stationary-Mileage-TEST-20261012/V3.092/
压缩包：artifacts/A300-406-V3.092-Stationary-Mileage-TEST-20261012.zip

- 完整烧录：Combined-N32L406CBL7.hex；BIN 替代文件起始地址 0x08000000。
- OTA 上传：A300-406-OTA-V3092.bin；沿用平台分离签名流程。
- 配套 App、Bootloader、ELF/MAP、镜像及交付 SHA256 清单、中文测试说明、实机测试表、自动验证诊断记录均已包含。
- ZIP SHA256：5b7b860e017f3804d49efe379f0d470a78eaba81e7f68b2cf223a50659fb919f。

完整烧录后首次启动执行工厂初始化，重置外部 Flash 中的配置、BCR、检查点和授权状态。已配置设备优先使用 OTA；完整烧录测试需重新核验参数。

## 实际软件验证

生产 Makefile 的 App、Bootloader 构建及发布门禁通过，使用 ARM GNU Toolchain 14.3.rel1。
本次 41 个相关 host 脚本均通过，0 失败、0 跳过。覆盖静止里程/GNSS/JT808、配置和盲区/外部 Flash、OTA transport/签名/续传/掉电、Bootloader 安装/回滚/工厂初始化，以及身份、RAM/Flash 与交付清单。未声称运行整个仓库所有测试。
首次 RAM 回归调用漏传 build 参数；补正后复测通过。初次结果与日志已保留。
所有具体命令及退出码见 diagnostics/host-results.json 和 host-logs。

App 105564 B；OTA 105596 B（含 32 B 头）；Bootloader 22556 B；Combined 130140 B。
校验了 HEX 每条记录的长度/校验和、地址范围、标准地址/入口记录及 EOF；三个 HEX 从各自 BIN 生成并逐字节还原一致。
校验了向量、工厂初始化记录、OTA 产品/3092 版本/长度/CRC，及 Combined 内 App 与 OTA payload 的完全一致性。
ZIP CRC、全部交付文件长度/SHA256 和压缩内容与清单的一致性已检查。

App Flash 剩余 932 B，LOW_HEADROOM/CONFIGURATION_CHANGED 仍存在且旧基线不可直接比较。
RAM 门禁运行余量 4104 B，门槛 4096 B；审核执行根 complete。独立 stack-analysis 仍 incomplete，这个诊断状态没有被隐藏，见 ram-budget.json。
资源余量较紧，实际内存水位、长期运行、传感器、Bootloader 跳转及 OTA 安装仍需要实机/HIL 验证。

## 源码改动与操作边界

本次版本交付修改 release_identity.json、include/config.h、include/build_version.h；同步 tools/release_guard.py 中仅版本身份的审核指纹及 tools/tests/test_release_identity_contract.py。
保留前一轮 src/mileage.c、里程/GNSS/JT808 测试与修复文档，新增本次计划、交付文档及新产物；没有修改主循环、硬件引脚或协议运行逻辑。
旧交付包未覆盖。本次未烧录设备、上传 OTA 平台、启动服务、部署、提交或推送。
