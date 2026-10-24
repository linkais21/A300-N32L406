# A300-406 V3.093 超速预警固件交付

完整版本：`T360-A300_406_20261015162913,V3.093`；OTA 计数 `3093`；设备型号 `A300-406`；MCU `N32L406CBL7`。
包含已有静止里程修复及本轮 0x005B 设置、保存、查询、实际超速预警。

## 交付

目录：`artifacts/A300-406-V3.093-005B-SpeedWarning-TEST-20261015/V3.093/`。

- 完整烧录：`Combined-N32L406CBL7.hex`；或 `Combined-N32L406CBL7.bin`，BIN 起始地址 `0x08000000`。
- OTA 上传：`A300-406-OTA-V3093.bin`，沿用现有平台分离签名流程。
- 压缩包：`artifacts/A300-406-V3.093-005B-SpeedWarning-TEST-20261015.zip`。
- ZIP SHA256：`282bdc9327f11ae6d05c3b9dd1111087df761d9043f7279e43121ddfd1af577a`。

包内包含 81 个文件：完整烧录和 OTA 文件、App/Bootloader、ELF/MAP、中文操作说明、0x005B 审核记录、HIL 待填表、49 项 host 日志、源码输入身份、构建及资源诊断、镜像验证记录和 SHA256 清单。

**完整烧录首次启动执行工厂初始化，重置外部 Flash 配置、BCR、检查点及授权状态。**
已有配置设备可使用 OTA 保留配置；烧录使用 Combined，上传平台使用 OTA BIN，两者用途不同。

## 验证

使用 `tools/build_dev_release.py`、生产 App/Bootloader Makefile 和仓库 `.toolchain`，完整 release-gate 通过。
对最终源码输入运行 49 个相关 host 脚本：49 通过、0 失败、0 跳过。
覆盖参数事务/预警/双通道 JT808、里程/GNSS、配置 NOR 掉电、盲区/外部 Flash、签名信任/OTA 续传/安装掉电/回滚、工厂初始化、资源和交付契约。
具体命令、退出码、耗时、源码 SHA256 见包内 `diagnostics/host-results.json` 和 `source-identity.json`。

初次包核验发现构建器直接输出的 ELF HEX 省略填充区，而 BIN 的这些字节为 0：App 有 8 字节、Bootloader 有 7712 字节差异。
交付的三个 HEX 均从最终 BIN 生成，保留这些填充字节；使用 `.data` 节地址和真实复位入口，逐条检查长度/校验和/地址/入口/EOF，逐字节还原一致。
Bootloader 使用启动版本计数而不嵌入完整版本字符串；已核对最终 ELF 中传入 `boot_startup_status()` 的 3093 立即数及其在交付 BIN 中的实际指令字节。
App/Combined 嵌入完整版本一致，OTA 头产品/3093 版本/长度/CRC 正确，OTA payload 与 Combined 的 App 区域完全一致。
ZIP CRC、81 个压缩条目与目录文件字节、交付清单长度/SHA256 均已校验。

镜像大小：App 105936 B；OTA 105968 B（含 32 B 头）；Bootloader 22556 B；Combined 130512 B。
Flash 余 560 B，保留 LOW_HEADROOM 提示；完整 RAM 预算余量 4104 B，门槛 4096 B。
审核执行根 complete；独立栈图仍为 incomplete，诊断未隐藏，见包内 `ram-budget.json`。

尚未执行本镜像的实机/HIL 测试。需要核验实际烧录启动、OTA 安装、平台 bit13 显示、真实速度门槛、GNSS/休眠恢复、盲区补传和运行水位。
本包为软件验证完成、实机待测的固件包，不表示实机验收或线上发布完成。

## 本次改动边界

在前一轮 0x005B 改动之上，本次交付修改：

- `release_identity.json`、`include/config.h`、`include/build_version.h`：推进 V3.093/3093 及构建时间。
- `tools/release_guard.py`：仅同步两个版本身份文件的审核指纹和注释。
- `tools/tests/test_release_identity_contract.py`：同步版本契约。
- 本交付说明、对应计划、新交付目录/ZIP/SHA256。

构建、回归和打包脚本及本轮前身份备份位于忽略的 `build-v3093-delivery/`，不改变现有生成器运行契约。
本次没有继续修改预警、里程或其他业务源码。已有用户修改保留，旧固件交付包未覆盖。
未烧录、上传平台、部署、提交或推送。
