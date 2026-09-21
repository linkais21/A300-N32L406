# 日志字段、创建时间和静态漂移移植

本轮在已有 V3.055 工作树上修改，未回退到设备当前显示的 V3.054。保留既有修改；未提交、部署或烧录。

## 行为与边界

- `R`：读取硬件 RTC，输出 `HHMMSS`，非法时分秒回退为 `000000`。现有 NTP 逻辑只修正保留定位时间，未发现同步硬件 RTC 的路径；本轮没有增加 RTC 校时或改变 STOP1 定时。此字段是硬件 RTC 当前值，不能据此宣称已与北京时间同步。
- `4C`：有效车辆电源 ADC 值，单位 0.1 V，四舍五入；无效、非有限或负值输出 0，超大值饱和为 65535。示例：12.36 V → 124。
- `6F`：本次模组会话已完成 SIM 身份查询、状态处于联网阶段且 ICCID 有效时为 0，否则为 1。接受驱动支持的 19/20 位十六进制 ICCID；非法字符串不进入报文。IMSI、OTA ID 子字段仍为空。状态来自当前模组会话缓存，本轮没有新增热插拔检测命令。
- 完整版本串的 14 位时间戳改为构建创建时的北京时间。Python/PowerShell 生成器同步维护 `release_identity.json`、`FW_FULL_VERSION` 和 `FW_VERSION_STR`，保留 V3.055 与 OTA 单调计数 3055。首次无依赖文件构建也先生成版本头；发布包脚本在 Make 完成后重新读取实际镜像身份。
- 静态漂移采用用户指定 G452 工程 `app/src/gps_report_filter.c` 的上报算法，适配 N32L406 的 `i2c_accel` 和 RMC 时间戳。使用固定参考默认值，未移入新的运行时参数配置接口。

静止判定：5 点加速度窗口，每 200 ms 最多读取一次；速度 ≤1 km/h、各轴窗口峰峰值 ≤30 mg 持续 30 s，且已有 5 个不同 RMC 样本后，用定位去极值均值锁定坐标。加速度峰峰值 ≥60 mg 或连续 3 个不同 RMC 速度 ≥2 km/h 时解除。定位/速度过期、传感器失败、采样间隔超过 1 s、关闭滤波或 GNSS、唤醒重置均清除证据。保留经度跨 ±180° 的处理。

实时主/备通道、查询应答、工作模式上报和采集时的盲区记录使用过滤快照；休眠前保留过滤坐标。已有历史盲区记录及历史定位回放不重新过滤。原始 GNSS 对象不被修改，原有里程与安全控制仍使用原始数据。

DA218E 按当前驱动 `>>4` 的 12 位 ±2g 数据适配，1024 LSB/g，拒绝零向量和满量程值。没有改 GPIO、地址、寄存器配置或休眠策略。候选坐标用 1e-7 度整数保存，与锁定坐标共用存储；每轴量化误差小于约 1.2 cm，最终上报仍遵循原协议精度。

## 构建和验证

构建目录：`build-detail-optimization/`。实际使用工作区已有 `tools/w64devkit/w64devkit/bin/make.exe`，目标 ARM GCC 14.3.1。

- `make all BUILD=build-detail-optimization`：通过，无编译告警。
- 日志字段和版本时间戳已观察到修复前失败、修复后通过。真实过滤器与 JT808 联合测试在移植前 `jt808.c` 上因漂移坐标上报失败，当前实现通过。
- 最终 25 项定向脚本全部通过：日志、版本生成与契约、漂移状态机和报文、GNSS 保留快照、JT808 双通道/首包/参数、盲区回放、STOP1 契约、终端身份、EC800M 身份恢复/URC/NTP/UDP、构建工具、Flash 配置、F39、FOTA 和功能开关。命令与退出码见 `build-detail-optimization/validation/commands-final.json`。
- 独立执行 `libc_parser_guard.py` 与 `test_platform_trust_anchor.py` 均通过；后者覆盖真实平台签名及篡改拒绝。
- 二进制内的完整版本串与两个头文件、身份 JSON 一致，旧固定日期串已不存在。
- `git diff --check`：本轮范围通过。变更前快照、任务差异和最终源码 SHA256 留在构建目录，避免把已有未提交内容计入本轮变更。

生成镜像身份：`T360-A300_406_20260917193337,V3.055`。

App BIN：105848 字节；SHA256：`14c05d369b594e6ae0217bfbd811393a4b99eb0047f0ae290ea40037ad08ee48`。

为满足新增过滤器的 SRAM 预算，构建增加 `-fno-inline-functions-called-once`，避免单次调用服务的临时变量长期合并到 `main` 栈帧。Flash 门禁通过，但只剩 **648 字节**。静态 SRAM 为 18080 字节，已知最大调用帧和为 2400 字节，余量恰为 4096 字节。

**完整发布门禁未通过，不能作为已验证发布包交付。** `make release-gate` 的 RAM 检查仍报告全程序栈证据不完整：79 个缺失帧、53 个间接调用、180 个尾调用及 1 个调用环，尚无完整栈/堆/异常边界。改动前 `build-v3055-20260917/validation/release-gate.log` 已有同类未通过记录。本轮保留严格门禁，未降低阈值或将诊断模式当作验收。

## 本轮文件

- 日志：`src/log_platform.c`、`src/ec800m.c`、`include/ec800m.h`。
- 定位：新增 `src/gps_report_filter.c`、`include/gps_report_filter.h`；修改 `src/gps.c`、`include/gps.h`、`src/jt808.c`、`src/main.c`。
- 构建和版本：`Makefile`、`gen_version.ps1`、`tools/build_dev_release.py`、`tools/release_guard.py`、`release_identity.json`、`include/build_version.h`、`include/config.h`。
- 新测试：`tools/tests/gps_report_filter_host.c`、`test_gps_report_filter.py`、`test_gps_report_wire.py`。
- 更新测试（均在 `tools/tests/`）：`test_log_platform_wire.py`、`test_build_version_refresh.py`、`test_release_identity_contract.py`、`test_gps_ntp_apply.py`、`test_acc_stop1_contract.py`、`test_blind_zone_replay.py`、`test_jt808_dual_session.py`、`test_jt808_first_location.py`、`test_terminal_identity.py`。
- 本文。试验过的其他源码调整已恢复为本轮开始时的内容。

## 需要实机/HIL 验证

1. 抓取日志 UDP 并核对平台 `R/4C/6F` 显示；RTC 当前值/时区、电压与万用表比对、SIM 重启恢复。
2. 室外停车与遮挡漂移、低速蠕行、起步、振动、GNSS 丢失恢复、ACC 开关和休眠唤醒；确认锁定/释放时延及持续主循环采样频率。
3. 联网阻塞、AT 超时、FOTA 和 F39 并发负载下的栈/堆水位、ISR 开销与看门狗行为。主机测试和静态已知帧统计不能替代此项。
