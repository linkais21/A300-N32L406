# V3.058 静止漂移诊断 / 长期挂机 HIL 测试包

版本：T360-A300_406_20260918103729,V3.058，版本计数 3058。
本包用于用户已明确要求的专用设备烧录测试。静止滤波阈值未改，本版增加 GPS-DRIFT 诊断，尚未确认修复漂移。
release_approved=false；完整 release-gate 因全程序栈证据不完整未通过，不是生产发布包。

## 烧录

**Combined / Bootloader 首次启动会执行既有出厂初始化，清除设备配置、BCR、OTA 断点及授权记录。先保存参数，启动后重新配置。**

推荐在已有 N32L406 SWD 烧录工具中选择 Combined-N32L406CBL7.hex；HEX 自带地址，执行下载并校验，然后复位。不要使用 N32G452 的目标配置。

| 文件 | BIN 烧录起始地址 | 说明 |
| --- | --- | --- |
| Combined-N32L406CBL7.hex / .bin | 0x08000000 | Bootloader + 当前 App，供完整测试设备初始化 |
| App-N32L406CBL7.hex / .bin | 0x08006000 | 仅 App；只有已处理 Bootloader/BCR 镜像身份一致性时才使用 |
| Bootloader-N32L406CBL7.hex / .bin | 0x08000000 | 沿用已校验的 V3.057 包 Bootloader，源码比对一致 |

不要将原始 App BIN 直接上传 OTA 平台，本包不含 OTA 上传包。本轮未连接或烧录设备。

## 长期挂机观察

1. 调试串口使用 115200、8N1。上电确认显示 V3.058 和编译时间 2026-09-18 10:37:29；不要仅凭文件名确认版本。
2. 完成原有服务器/终端参数配置、确认入网定位后，固定设备，连续保存至少 24 小时串口日志和同时间段平台位置记录。日志保存在电脑，不要回写程序 Flash。
3. REALTIME 模式下每 30 秒输出 GPS-DRIFT。s=3 且 use=1 表示诊断瞬间锚点生效；反复 s=1/2 或 use=0 时结合 b/span/t 排查。字段定义见 DIAGNOSTICS.md。休眠时该日志停更本身不等于故障。
4. 观察 HEALTH 的 STK_PEAK、RAM_GAP、RAM_AVAIL、HEAP_USED，记录重新出现的 BOOT/复位原因、定位失效、掉线及恢复时刻。先按设备正常供电和原有工作模式测试，勿为保持日志而擅自改变唤醒策略。
5. 完成固定测试后，再单独验证起步、低速挪动、停止、ACC/休眠唤醒及断网恢复，记录人工操作时间，以区分真实运动和漂移。

## 验证与容量

App 106420/106496 B，Flash 剩余 76 B，容量硬检查通过但 LOW_HEADROOM 告警存在。该余量不会随挂机时间增长逐渐用完；它不是运行时 RAM 或外部日志存储余量。
静态 SRAM 17756 B、已知调用帧合计 2408 B，估算剩余 4412 B；全程序栈/堆/异常边界未证明，因此 RAM 发布门禁未通过。长期稳定性需要实机/HIL 验证，不能据此保证稳定。

10 项定向脚本最终通过：GPS 滤波、GPS/JT808 线报文、休眠时间戳/振动契约、生产 GNSS、版本契约、内部 Flash 布局、外部 Flash 布局、Boot 冷启动恢复、Combined 烧录脚本、开发包 manifest。
最初版本测试仍固定 V3.057，已随版本升级同步为 V3.058；身份门禁哈希经比对仅版本/时间戳变化后同步。初始失败保存在 validation。曾尝试不存在的 test_release_guard.py，记录为命令错误，不计入通过数；实际 release-guard 在 release-gate.log 中通过。

源码快照包括 App 自有源码、Bootloader 源码和本轮相关测试；SDK/工具链沿用工作区，完整构建选项见 flash-build-profile.json。SHA256SUMS.txt、MANIFEST.json 用于检查包完整性。
