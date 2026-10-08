# A300-406 V3.091 验证测试包

版本：T360-A300_406_20261008174141,V3.091；OTA 版本计数：3091；设备型号：A300-406。
本包含本轮 0x8103 参数补齐和已完成对接的 AGNSS 代码，修复了 IRQ 审核指纹失配。
软件发布门禁通过；本包实机验证待执行，release_approved=false。

## 选择测试方式

| 用途 | 文件 | 用法 |
|---|---|---|
| 从现有 V3.090 升级，保留配置 | A300-406-OTA-V3091.bin | 上传现有 FOTA 测试平台，型号 A300-406，版本计数 3091；平台提供分离签名 |
| 完整 SWD 烧录 | Combined-N32L406CBL7.hex | 自带绝对地址，起点 0x08000000，包含 Bootloader 和 App |
| 工具只接受 BIN 时完整烧录 | Combined-N32L406CBL7.bin | 起始地址 0x08000000 |
| 单独 App 分析/验证 | App-N32L406CBL7.hex / .bin | App 起点 0x08006000；单独 SWD 替换 App 绕过 OTA 回滚流程 |

**完整 Combined 烧录后，首次启动会执行工厂初始化，重置外部 Flash 中的配置、BCR、检查点和授权状态。**
已配好服务器、AGNSS 参数的设备优先使用 OTA。完整烧录测试应重新配置并核验所需参数。
所有 HEX 从同一 BIN 生成，显式写入填充字节；Combined 的 App 与 OTA payload 完全一致。

## 已自动验证

- 212 个当前固件/门禁 host 脚本通过，0 失败，0 跳过；不含 4 个不适用于本镜像的历史/非当前构建脚本，原因记录在 diagnostics/host-results.json。
- App、Bootloader 构建通过；release-gate、Bootloader 容量检查通过；平台实际签名验证及篡改拒绝通过。
- RAM：静态 16056 B + 对齐 4 B + 硬堆保留 1024 B + 启动/主循环栈 2804 B + 最坏嵌套异常 584 B；完整运行余量 4104 B，要求 4096 B。
- Flash：App 105532/106496 B，剩余 964 B；LOW_HEADROOM 和 CONFIGURATION_CHANGED 告警仍存在。
- HEX 地址、每行校验、完整字节、向量、工厂初始化记录、OTA 型号/版本/长度/CRC 和 App 一致性已验证。
- ELF/MAP 与 RAM 证据匹配；SHA256SUMS-N32L406CBL7.json 给出镜像哈希，delivery-manifest.json 覆盖全部交付文件。

standalone stack-analysis.json 仍显示 incomplete，源于辅助不可达函数和其报告范围。
发布 RAM 判定使用 ram-budget.json：启动、主循环、中断的可达调用根均完整，并计入硬堆保留及五级异常栈，最终门禁为 pass。

## 实机验证与正式版判断

你已确认 AGNSS 对接完成、注入已生效，记录为模块人工验证通过。
V3.091 新增参数及本包镜像尚未完成实机验收，当前交付是测试候选。
请填写“实机验证记录.md”，确认本包 OTA、0x8103、重启保持、实际告警时机、RAM 水位及稳定性后再放行正式版。
既有 V3.081 日志有下载/安装断电恢复证据；该记录不覆盖本包，下载断网实机恢复仍需补证。
Flash 余量与 RAM 超出门槛仅 8 B 的情况也需纳入正式版容量和压力测试评估。

## 本轮修改范围

- tools/exception_stack_guard.py：复核中断/启动函数和 NVIC 策略后更新 main.c 审核指纹。
- tools/tests/test_ram_release_budget.py：补充 main.c 指纹失配拒绝路径。
- release_identity.json、include/config.h、include/build_version.h：V3.091/3091 身份。
- tools/release_guard.py、tools/tests/test_release_identity_contract.py：同步版本审核与测试。
- tools/tests/test_build_dependencies.py：配置变化探针改用不同于默认 -g3 的 -g1。
- tools/tests/test_f39_end_to_end.py：补齐启动诊断所需的 UART/DMA/GPIO 寄存器夹具。
- tools/tests/test_flash_gate_build.py：临时构建复制完整门禁依赖。
- tools/tests/test_lto_stack_guard.py：缺少编译配置证据的拒绝测试对齐真实拒绝原因；未知可达调用仍由真实 ELF 拒绝路径覆盖。
- tools/tests/test_nmea_replay.py：纯解析夹具增加直通滤波接口，使关联 GNSS 回放可链接；生产滤波模块由独立测试覆盖。
- 计划、诊断与交付说明。保留原有工作树改动；没有修改本轮以外的生产运行逻辑。

诊断记录保留初次失败、夹具修复后的复测和最终发布门禁结果。
既有固件交付文件未覆盖，本轮没有提交、推送、部署或烧录设备。
