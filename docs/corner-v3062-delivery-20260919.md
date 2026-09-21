# V3.062 拐角补传检查与交付

本轮检查发现算法未删除：`src/motion_corner.c` 仍参与 Makefile 构建，JT808 调度调用它，在线发送失败会进入盲区存储。V3.061 ELF 也包含 motion_corner_step 和相关状态。真正影响默认使用的是 `src/flash_config.c` 的 anglerep_en=0，以及 `src/at_config.c` 的 ANGLEREP 只回复 OK、未改参数。

本轮改动：

- `src/flash_config.c`：新配置默认开启拐角补传。
- `src/at_config.c`：本地串口 `ANGLEREP=ON|OFF|1|0` 真正保存开关；保存失败恢复 RAM、回复 ERR:SAVE；缺少或多余参数回复 ERR:ARG。复用原有 AGPS 开关处理，保留其行为。
- `tools/tests/test_at_config_serial_f39.py`：开启、关闭、重复调用、非法参数、保存失败回滚。
- `tools/tests/test_flash_config_v3.py`：空白 Flash 默认开启；保存关闭/开启后重启保持。旧设备 OTA 不覆盖已有配置。
- `release_identity.json`、`include/build_version.h`、`include/config.h`、`tools/tests/test_release_identity_contract.py`、`tools/release_guard.py`：V3.062/3062 身份及经审核的身份摘要。
- 新增 `build/corner-v3062-20260919/` 独立快照、构建/验证/打包脚本、日志及本说明；新交付目录和 ZIP 不覆盖旧包。

原算法、JT808 调度、Flash 格式和所有权机制没有修改。角度字段存在既有差异：配置结构 anglerep_angle 默认 30，而实际算法使用累计 20 度及同向确认；当前调度未读取该角度字段。本轮沿用实际算法，不将旧字段值描述成有效阈值。仅修复开关，不新增角度配置协议。

修复前，新增串口回归在 `ANGLEREP=ON` 后的启用断言失败；修复后通过。`check_regression_baseline.py` 又在保留的 V3.061 源码快照上运行两项新回归，分别复现命令无效和出厂默认未开启，失败断言与日志见 `validation/red-results.json`。未回滚用户工作树。范围内自审以 V3.061 快照为基线核对，保存失败、现有 AGPS、输入拒绝和 OTA 配置保持均有回归。

使用：完整烧录 `SWD-Combined-V3062.hex` 或 BIN（0x08000000）；完整镜像首次启动会初始化配置等状态，应记录并恢复所需设备参数。OTA 上传 `A300-406-OTA-V3062.bin`，deviceModel=A300-406、versionCode=3062，平台生成分离签名。旧设备原来关闭的开关在 OTA 后仍关闭，需要在调试串口 115200/8N1 发送 `ANGLEREP=ON` 加回车，收到 OK 后保存生效。该命令不作为短信或 JT808 命令使用。

实际执行 `python build/corner-v3062-20260919/build_test.py`：65 个测试脚本通过，App/Bootloader 无编译 warning；身份、信任锚、Flash、Boot 静态 RAM、帧预算和范围内 diff-check 通过。App 106324 B，分区余量 172 B；OTA 106356 B。完整 release-gate 退出 2，仍因整体栈/堆/IRQ 证明不完整拒绝：静态 RAM 17716 B、main 已知调用帧和 2536 B（非上限）、缺失帧 68、间接转移 67、尾转移 131、调用环 1。没有豁免门禁，release_approved=false、hardware_verified=false。

`python build/corner-v3062-20260919/package.py` 核对当前输入哈希、最终 Boot/App 向量、工厂初始化记录、合并偏移、三份 HEX 的地址/校验和/BIN 一致性、OTA 头/CRC/版本/载荷、包内文件哈希及 ZIP 内容。交付 `artifacts/A300-406-V3.062-Corner-HIL-20260919.zip`，SHA256 为 `5fe55d1340dbe5fc4685e301dadc5a4146c9e0d7dfe44348f828e94174cf1656`。

需要实机/HIL 验证：默认开启后的道路转弯补点、旧配置经命令开启后的转弯、断网转弯后的补传、冷启动、保存后重启保持、实际 OTA 下载验签切换、长时间运行。没有上传平台、下发设备命令、烧录、提交或推送。
