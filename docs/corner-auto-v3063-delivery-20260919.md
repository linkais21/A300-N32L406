# V3.063 拐角补传自动开启

用户明确要求无需指令开启，本版替代 V3.062 的使用方式。完整烧录、旧设备 OTA 及后续重启均自动启用；旧配置即使保存 anglerep_en=0，也在启动装载完成后置 1。不是只改出厂默认值，不需要用户发送 ANGLEREP。

本轮源码修改 `src/flash_config.c`：原装载过程提取为私有 cfg_load，公共 cfg_init 在所有装载返回路径完成后设置运行时开关。保持原 A/B 选择、CRC、掉电恢复、旧格式迁移和其他配置；不新增 Flash 擦写。旧 ANGLEREP=OFF 若使用只对当前运行周期有效，重启重新启用。算法、有效定位/速度门槛、限频和盲区存储不变。

`tools/tests/test_flash_config_v3.py` 增加旧关闭配置重启自动启用、其他字段逐字节保持、重复启动不新增擦写的回归。修改实现前，当前源码运行新断言失败；修改后通过。`build/corner-auto-v3063-20260919/check_regression_baseline.py` 对保留的 V3.062 快照再次验证 RED，并保留日志。本轮以该快照审查差异，不覆盖或回滚已有用户修改。

同步修改版本身份文件 `release_identity.json`、`include/config.h`、`include/build_version.h`、`tools/tests/test_release_identity_contract.py` 和 `tools/release_guard.py`，版本 V3.063、计数 3063。新增独立构建/打包目录 `build/corner-auto-v3063-20260919`、交付目录和本说明；未覆盖 V3.062 包。

烧录使用 SWD-Combined-V3063.hex（自带地址），或 BIN（0x08000000）。完整烧录包首次启动会初始化配置等状态，应记录并恢复需要的参数。OTA 上传 A300-406-OTA-V3063.bin，deviceModel=A300-406、versionCode=3063，平台生成分离签名；OTA 保留其他配置。

执行 `python build/corner-auto-v3063-20260919/build_test.py`：65 个测试脚本通过，App/Boot 构建无编译 warning，身份、信任锚、Flash、Boot RAM、帧预算、diff-check 通过。App 106376 B，分区剩余 120 B；OTA 106408 B。完整 release-gate 退出 2，仍因栈/堆/IRQ 证明不完整拒绝（静态 RAM 17716 B、已知调用帧和 2536 B 非上限、缺失帧 68、间接转移 67、尾转移 130、环 1）。不豁免，release_approved=false、hardware_verified=false。

执行 `python build/corner-auto-v3063-20260919/package.py`：输入哈希、向量/工厂初始化、HEX/BIN 一致性、OTA 头/CRC/版本/载荷、ZIP 完整性和内容哈希检查通过。ZIP SHA256：`df7cf45cef43254da0ad3ffe2ca182aae62c55fee5d393ccf6fd22267152d5ac`。需要实机/HIL 验证旧关闭配置 OTA 后无需指令转弯补传、冷启动、断网恢复补传及真实 OTA 切换。本轮未烧录、上传平台、下发设备控制、提交或推送。
