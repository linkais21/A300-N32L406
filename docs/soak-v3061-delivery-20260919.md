# V3.061 烧录与 OTA 挂机测试交付

版本 `T360-A300_406_20260919001442,V3.061`，计数 3061。用户授权先交付测试固件，后续再做第八轮；本轮没有开展第八轮优化。

交付 `artifacts/A300-406-V3.061-Soak-HIL-20260919.zip`，SHA256：`ebd24dc7e5b70bbb31b52da53db673aa03eac1831ef6cb65575a93137c9f1f5a`。

- 完整烧录：`SWD-Combined-V3061.hex`，自带地址；BIN 起始地址 0x08000000。
- OTA 平台上传：`A300-406-OTA-V3061.bin`，106324 B，型号 A300-406，versionCode=3061；完整版本字符串及上传参数见包内 `OTA-upload.json`。该文件是含 32 字节头的上传包，分离签名由平台生成，不能直接当 SWD App 烧录。
- App：106292 B，分区余量 204 B。两种交付方式的 App 载荷逐字节一致。
- Combined 首次启动初始化配置 A/B、BCR、OTA 断点及授权状态；烧录前记录参数，启动后恢复配置。OTA 应从较旧版本验证；先烧录 V3.061 后通常不能再测试同版本升级。

## 改动范围

`release_identity.json`、`include/build_version.h`、`include/config.h` 仅版本/时间戳更新；`tools/release_guard.py` 同步经范围内差异审核的身份文件摘要；`tools/tests/test_release_identity_contract.py` 同步版本断言。

`tools/tests/test_fota_modem_handoff.py` 修正旧测试契约：模拟 `+QIOPEN: 1,565` 的失败应返回 -1 并释放通道；异步接收测试需要推进 RX、状态机和时间至有界超时，而非仅调用三次后认为成功。保留后续 OTA 启动、旧事件不影响新连接和事务期间禁止 OTA 接管的断言。原测试先失败，修正后通过；没有修改 modem/FOTA 运行代码。

新增本说明、`build/soak-v3061-20260919/` 中的独立构建/打包脚本、输入快照、原始失败日志与最终验证记录，以及新的交付目录/ZIP/校验文件。保留已有修改及旧交付包；未提交、推送、上传平台、下发任务或烧录设备。

## 实际验证

`python build/soak-v3061-20260919/build_test.py` 首次在过期 modem 交接测试失败后停止；调查并修正夹具后通过 `--resume` 继续，复用输入未变化的前序通过记录，保留失败记录。最终 57 个测试脚本（含帧预算）通过。App 使用当前 Makefile、ARM GNU 14.3.rel1、固定版本头独立构建；Bootloader 从同一输入快照独立构建，均无编译 warning。

身份门禁、平台信任锚、Flash 容量、Boot 静态 RAM、libc parser、帧预算通过。完整 `release-gate` 退出 2，仍因整体栈/堆/IRQ 证明不完整而拒绝：静态 RAM 17716 B、main 已知帧和 2536 B（非上限），缺失帧 68、间接转移 67、尾转移 131、环 1。未豁免门禁；`release_approved=false`、`hardware_verified=false`。

`python build/soak-v3061-20260919/package.py` 核对当前构建输入哈希、最终 ELF 身份、Boot/App 向量、当前 Boot 工厂初始化 section/记录、合并偏移、三个 HEX 的逐地址 BIN 一致性、OTA 头/长度/CRC/版本/载荷、包内 SHA256 与 ZIP 完整性。早期 factory artifact 测试还会读取仓库既有 Boot 构建；本次交付 Boot 的有效性另由上述最终打包检查验证，未将旧产物测试作为唯一依据。

需要实机/HIL 验证冷启动、真实 OTA 签名/下载/切换、配置保持、网络重连、定位上报、休眠唤醒及长时间运行。包内 README 提供建议 24 小时起、可延长至 48–72 小时的挂机步骤和日志项。水位观测不能代替最坏栈预算证明。

第八轮后续以本 V3.061 源码为基线继续；第七轮旧版本 ELF/BIN 的相同哈希结论不能套用于本次已更新版本身份的产物。
