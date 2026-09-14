# 本轮自动验证

- 全量 ARM Bootloader、V3.040、V3.041 构建通过，无编译器 warning/error。
- 两版 release identity、Flash capacity、Boot RAM guard、libc parser 检查通过。
- 两版 release-gate 在 RAM 阶段失败，退出 2；失败状态保留在 manifest。
- 实际 EC800M C 驱动五条 DMA 边界路径通过；共享 SHA 181 个摘要对照通过。
- 真实平台公钥签名验证和篡改拒绝测试通过。
- 两版 manifest 中全部文件的大小/SHA256、OTA 包头/版本/CRC、App 字节一致性通过。
- Combined 中 Boot/App 偏移及填充检查通过，HEX→BIN 回转逐字节一致。
- ELF 符号核对：V3.040 保留 fota_sha_block/sh_up；V3.041 使用 sha256_block/update/final。
- 实机挂测、SWD 回读、真实 OTA 下载/升级和断电恢复：未执行，需要实机/HIL 验证。
