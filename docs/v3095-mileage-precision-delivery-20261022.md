# V3.095 里程精度修复固件交付

完整版本：`T360-A300_406_20261022085510,V3.095`；计数 `3095`；MCU `N32L406CBL7`。

交付目录：`artifacts/A300-406-V3.095-Mileage-Precision-TEST-20261022/V3.095/`。

- 完整烧录：`Combined-N32L406CBL7.hex`；Combined BIN 地址 `0x08000000`。
- OTA 上传：`A300-406-OTA-V3095.bin`，产品 `A300-406`，沿用平台分离签名流程。
- 压缩包：`artifacts/A300-406-V3.095-Mileage-Precision-TEST-20261022.zip`。
- ZIP SHA256：`f527537296717a369c28707db128d449cb46da5619c8701bf6e064925cb61c1a`。

修复逐段整米截断：保留有效行驶距离的毫米余数，满一米再计入原计数器。
原防漂、静止与跳点判断保持，Flash/配置格式和 JT808 单位未改变，历史少计不回填。
包含 V3.094 已有修复；可从 V3.093/3093 或 V3.094/3094 向上进行正常 OTA。

**已有配置设备优先使用正常 OTA（保留原配置及累计里程）；Combined 完整烧录
首次启动会执行工厂初始化并重置外部 Flash 配置、授权、里程等状态。**
包内 `README-烧录与OTA说明.md` 提供用途、地址、签名和验收步骤。

已自动验证：真实 C RED→GREEN；77 项选定回归通过、0 失败、0 跳过；
App/Bootloader 编译、release-gate、Flash/RAM、平台签名信任均通过。
首轮唯一失败是旧转弯 host 测试夹具缺少 stddef.h，补齐头文件后重跑通过；
生产转弯逻辑和断言未改，首次记录与修复原因保留在 diagnostics。
HEX/BIN 逐字节、版本/计数、地址/向量、初始化请求、OTA CRC/产品/payload、
发布清单、127 个 ZIP 文件均已验证。

App 106368 B，Flash 剩余 128 B；静态 SRAM 15968 B；完整运行间隙 4188 B，
门槛 4096 B。独立栈诊断 incomplete，审核执行根 complete，完整 RAM 门禁 pass。
相对本轮起始版本增加 32 B Flash、4 B 静态 SRAM。门槛未放宽。

需要实机/HIL 验证：同路线独立里程对照、静止/低速/转弯/起步、网络等待、
失去定位恢复、OTA 安装和掉电重启。未烧录、未上传平台、未运行真实 OTA。
RAM 余数复位最多丢失 0.999 m；既有未落盘整米的掉电/部分复位损失仍存在。
不承诺本次轨迹的全部 2.813 km 差异均由此修复，也不修改历史里程。

本轮实际触碰的源码/测试/文档：

- `include/build_version.h`
- `include/config.h`
- `release_identity.json`
- `src/mileage.c`
- `tools/release_guard.py`
- `tools/tests/test_mileage_quantization.py`
- `tools/tests/test_motion_corner_policy.py`
- `tools/tests/test_release_identity_contract.py`
- `tools/tests/test_mileage_fractional.py`
- `docs/mileage-precision-20261022.md`
- `docs/superpowers/plans/2026-10-22-v3095-mileage-delivery.md`
- `docs/v3095-mileage-precision-delivery-20261022.md`

其他生成文件均在独立 build-v3095-delivery 和上述新交付目录。
19 个既有 ZIP/摘要文件 SHA256 不变，用户原始轨迹表 SHA256 不变。
按本轮开始时快照复核，其他既有源码未被覆盖。git diff --check 通过。
没有提交、推送、部署、设备控制或烧录。
