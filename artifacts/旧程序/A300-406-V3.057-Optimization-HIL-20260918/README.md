# V3.057 优化整合 HIL 测试包

版本：T360-A300_406_20260918100226,V3.057，计数器 3057。

合入高频日志分级与 libc exit/stdio 清理链移除；保持内联阈值 64 和坐标/非坐标精度策略。
App 106160 B，Flash 余 336 B；静态 RAM 17756 B。

**仅供专用测试设备：release_approved=false。完整 release-gate 因全程序栈证据不完整失败，需要实机/HIL 验证。**
34 个相关主机测试脚本最终通过。全部初始失败、修复后结果及门禁日志见 validation；具体合入范围见 CHANGELOG.md。

烧录文件：Combined-N32L406CBL7.hex 自带地址。BIN 地址：Combined/Bootloader 为 0x08000000，App 为 0x08006000。
**完整烧录 Combined/Bootloader 将触发既有出厂初始化，清除配置、BCR、OTA 断点及授权记录。先保存参数，烧录后需重新配置。**
本次未烧录、未部署；不含 OTA 平台上传包。不要将原始 App BIN 直接用于平台上传。

确认启动显示 V3.057，验证入网/定位/命令回复、里程、AGNSS/OTA、ACC 休眠唤醒、24 小时运行及栈/堆水位。
源码快照见 source，完整性清单见 MANIFEST.json；ZIP 不包含密钥或设备参数。
